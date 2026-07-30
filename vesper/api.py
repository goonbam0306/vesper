"""Loopback System API bootstrap subset."""

from __future__ import annotations

import re
import secrets
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ensure_runtime_dirs, vesper_home
from .storage import Storage
from .kernel import Kernel, KernelError, ProcessExecutionOutcome, ProcessStatus
from .memory import MemoryStore
from .context import ContextPack
from .model_runtime import CognitiveRuntime, ModelRegistry, CognitiveRequest, ProviderAdapters, ModelRoute
from .syscalls import SyscallEngine, SyscallRequest, SyscallError, ApprovalDecision, EffectStatus
from .core_apps import CoreApps, CoreAppError
from .connections import ConnectionStore, ConnectionError
from .mcp_gateway import MCPGateway, LocalCustomMCPSandbox
from .artifacts import ArtifactStore
from .secret_store import SecretStore, SecretStoreError
from .provider_adapter import ProviderAdapter, ProviderConnection
from .conversations import ConversationStore
from .lanes import (
    LaneDefinition,
    LaneDuplicateError,
    LaneError,
    LaneInvalidError,
    LaneNotFoundError,
    LaneRegistry,
    LaneVersionNotFoundError,
)
from .lane_invocations import LaneInvocationStore, LaneInvocationError
from .routing_proposals import MainLLMRouter, MainLLMRouteResult, RoutingDispatcher, RoutingDispatchResult
from .candidate_review import CandidateReviewError, CandidateReviewStore, review_payload


class RuntimeConfigurationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class Runtime:
    def __init__(self, home: Path | None = None, *, secret_store=None) -> None:
        self.home = home or vesper_home()
        ensure_runtime_dirs(self.home)
        self.storage = Storage(self.home / "vesper.sqlite3")
        self.kernel = Kernel(self.storage)
        self.memory = MemoryStore(self.storage)
        self.models = ModelRegistry(self.storage)
        self.lanes = LaneRegistry(self.storage)
        self.lane_invocations = LaneInvocationStore(self.storage, self.lanes)
        self.secret_store = secret_store or SecretStore()
        self.providers = ProviderAdapters(self.secret_store)
        self.cognitive = CognitiveRuntime(self.storage, self.kernel, self.memory, self.models, self.providers)
        self.lane_invocations.bind_cognitive_runtime(self.cognitive)
        self.routing = MainLLMRouter(self.cognitive, self.lanes)
        self.routing_dispatcher = RoutingDispatcher(self.storage, self.lanes, self.lane_invocations)
        self.conversations = ConversationStore(self.storage)
        self.syscalls = SyscallEngine(self.storage, self.kernel)
        self.core_apps = CoreApps(self.storage)
        self.connections = ConnectionStore(self.storage, artifact_store=ArtifactStore(self.home, self.storage))
        self.mcp_gateway = MCPGateway(self.storage, self.connections)
        self.candidate_reviews = CandidateReviewStore(self.storage)
        self.bootstrap_token = secrets.token_urlsafe(32)

    def start(self) -> None:
        """Start storage and reconcile every recoverable Kernel-owned state.

        Recovery is deliberately ordered: durable terminal intents are applied
        first; any remaining in-flight process is paused rather than guessed
        complete. The same pass also reconciles graph/wait metadata through the
        Kernel recovery hook, so restart cannot silently lose uncertainty.
        """
        self.storage.migrate()
        self.storage.start()
        self.startup_reconciliation = self.kernel.reconcile_startup()
        self.kernel._startup_reconciliation = self.startup_reconciliation

    def stop(self) -> None:
        self.storage.stop()

    def submit_director(self, prompt: str, conversation_id: str | None, client_request_id: str, *, principal: str = "director") -> dict:
        conversation = self.conversations.get(conversation_id) if conversation_id else self.conversations.create()
        if conversation is None:
            raise RuntimeConfigurationError("CONVERSATION_NOT_FOUND", "conversation not found")
        conversation_id = conversation["conversation_id"]
        self.kernel._submission_metadata = getattr(self.kernel, "_submission_metadata", {})
        self.kernel._submission_metadata[client_request_id] = {"conversation_id": conversation_id, "principal": principal, "input_ref": "conversation_message"}
        process = self.kernel.submit("director", client_request_id=client_request_id, priority="INTERACTIVE")
        user_message = self.conversations.append(conversation_id, "USER", prompt, process_id=process.process_id, client_request_id=client_request_id)
        def work(process_id: str):
            task_match = re.search(r"(?:할 일로|태스크로|task로)\s*(.+?)\s*(?:추가해줘|추가해 줘|추가해|만들어줘|생성해줘)\s*$", prompt, re.IGNORECASE)
            if task_match:
                title = task_match.group(1).strip().strip('\\"“”')
                try:
                    task = self.core_apps.create_task(title, request_id=f"{client_request_id}:action")
                except CoreAppError as exc:
                    content = "Task에 추가하지 못했습니다. 실제 저장에 실패했습니다."
                    assistant = self.conversations.append(conversation_id, "ASSISTANT", content, process_id=process_id, result_process_id=process_id, client_request_id=client_request_id)
                    return ProcessExecutionOutcome(ProcessStatus.FAILED, {"status": "ACTION_FAILED", "output": content, "action": {"entity_type": "task", "supported_chat_action": "CREATE_TASK", "commit_status": "FAILED", "error_code": getattr(exc, "code", "TASK_CREATE_FAILED"), "message": str(exc)}, "assistant_message_id": assistant["message_id"], "user_message_id": user_message["message_id"]})
                content = f"Task에 추가했습니다: {task['title']}"
                receipt = {"entity_type": "task", "action_type": "CREATE_TASK", "task_id": task["task_id"], "title": task["title"], "commit_status": "COMMITTED", "task": task}
                assistant = self.conversations.append(conversation_id, "ASSISTANT", content, process_id=process_id, result_process_id=process_id, client_request_id=client_request_id)
                return ProcessExecutionOutcome(ProcessStatus.COMPLETED, {"status": "ACTION_COMMITTED", "output": content, "action": receipt, "assistant_message_id": assistant["message_id"], "user_message_id": user_message["message_id"]})
            context_items = self.conversations.context_items(conversation_id, prompt)
            output = self.invoke_default_model(process_id, prompt, context_items=context_items)
            if not output or not output.strip():
                raise RuntimeConfigurationError("MODEL_EMPTY_OUTPUT", "model returned an empty response")
            attempt = self.storage.write(lambda c: c.execute("SELECT attempt_id FROM cognitive_attempts WHERE process_id=? ORDER BY created_at DESC LIMIT 1", (process_id,)).fetchone())
            attempt_id = attempt["attempt_id"] if attempt else None
            assistant = self.conversations.append(conversation_id, "ASSISTANT", output, process_id=process_id, result_process_id=process_id, attempt_id=attempt_id, client_request_id=client_request_id)
            return ProcessExecutionOutcome(ProcessStatus.COMPLETED, {"status": "MODEL_READY", "output": output, "assistant_message_id": assistant["message_id"], "user_message_id": user_message["message_id"], "attempt_id": attempt_id, "context_item_count": len(context_items)})
        self.kernel.register_handler(process.process_id, work)
        self.kernel.run_scheduler(max_slices=1)
        final = self.kernel.get(process.process_id)
        result = self.storage.write(lambda c: c.execute("SELECT outputs_json,effects_json FROM process_results WHERE process_id=?", (process.process_id,)).fetchone())
        payload = __import__("json").loads(result["outputs_json"]) if result else {"status": "FAILED", "output": "Vesper couldn't complete that request."}
        payload.update({"conversation_id": conversation_id, "process_id": process.process_id, "user_message": user_message, "process": final.__dict__ if final else None})
        if "empty response" in str(payload.get("error", "")).lower() or payload.get("status") == "FAILED" and payload.get("error") == "MODEL_EMPTY_OUTPUT":
            self.conversations.append(conversation_id, "ERROR", "Vesper가 응답을 생성하지 못했습니다.", process_id=process.process_id, result_process_id=process.process_id, client_request_id=client_request_id)
            raise RuntimeConfigurationError("MODEL_EMPTY_OUTPUT", "model returned an empty response")
        if "assistant_message_id" in payload:
            payload["assistant_message"] = next((m for m in self.conversations.messages(conversation_id) if m["message_id"] == payload["assistant_message_id"]), None)
        return payload

    def resolve_default_model_route(self) -> ModelRoute:
        settings = self.core_apps.settings()
        spec = settings.get("model_route") or {}
        if spec.get("status") != "configured":
            raise RuntimeConfigurationError("MODEL_NOT_CONFIGURED", "default model is not configured")
        connection_id = str(spec.get("connection_id", ""))
        model_id = str(spec.get("model_id", ""))
        if not model_id:
            raise RuntimeConfigurationError("MODEL_NOT_CONFIGURED", "default model is missing")
        if not connection_id:
            raise RuntimeConfigurationError("CONNECTION_NOT_FOUND", "default connection is missing")
        row = self.storage.write(lambda c: c.execute("SELECT * FROM provider_connections WHERE connection_id=?", (connection_id,)).fetchone())
        if row is None:
            raise RuntimeConfigurationError("CONNECTION_NOT_FOUND", "default connection is unavailable")
        if not row["credential_ref"]:
            raise RuntimeConfigurationError("CREDENTIAL_NOT_CONFIGURED", "default connection has no credential")
        return ModelRoute("default-runtime", model_id, row["provider"], frozenset({"text"}), "local" if row["endpoint_type"] == "local" else "remote", .9, 0.0, 1000.0, True, row["credential_ref"], row["base_url"], connection_id, row["api_style"], row["endpoint_type"], row["max_output_tokens"] if "max_output_tokens" in row.keys() else None)

    def invoke_default_model(self, process_id: str, prompt: str, *, context_items: list[dict[str, str]] | None = None) -> str:
        route = self.resolve_default_model_route()
        call_contract = {"prompt": prompt, "conversation_context": context_items or []}
        result = self.cognitive.invoke_model(process_id, CognitiveRequest(privacy="local_preferred"), call_contract, route=route)
        if not result.success or result.output is None:
            raise RuntimeConfigurationError(result.response.error or "MODEL_INVOCATION_FAILED", "default model invocation failed")
        return result.output

    def route_director_request(self, process_id: str, prompt: str, *, context_items: list[dict[str, str]] | None = None) -> MainLLMRouteResult:
        """Classify a Director request only; execution remains a later phase."""
        route = self.resolve_default_model_route()
        return self.routing.route(process_id, prompt, context=context_items or [], route=route)

    def dispatch_director_route(self, process_id: str, route_result: MainLLMRouteResult) -> RoutingDispatchResult:
        """Materialize a previously validated Director route; does not execute cognition."""
        return self.routing_dispatcher.dispatch(process_id, route_result)

    def route_and_dispatch_director_request(self, process_id: str, prompt: str, *, context_items: list[dict[str, str]] | None = None) -> RoutingDispatchResult:
        return self.dispatch_director_route(
            process_id,
            self.route_director_request(process_id, prompt, context_items=context_items),
        )



def create_app(runtime: Runtime | None = None) -> FastAPI:
    instance = runtime or Runtime()
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        instance.start()
        try:
            yield
        finally:
            instance.stop()

    app = FastAPI(title="Vesper", version="0.1.0", lifespan=lifespan)
    app.state.runtime = instance

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_shell():
        return HTMLResponse("""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Vesper Dashboard</title></head>
<body><main><h1>Vesper</h1><nav aria-label='Primary'><a href='/dashboard'>Today</a> <a href='/dashboard/lanes'>Lanes</a> <a href='/api/dashboard/today'>Dashboard API</a></nav><section id="today" aria-label="Today"><p>Local-first Director dashboard shell.</p></section></main></body></html>""")

    @app.get("/dashboard/lanes", response_class=HTMLResponse)
    def lane_dashboard_shell():
        return HTMLResponse("""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Vesper Lane Management</title></head>
<body><main><h1>Lane Management</h1><nav aria-label='Primary'><a href='/dashboard'>Today</a> <a href='/dashboard/lanes'>Lanes</a></nav>
<section id='lane-registry' aria-label='Lane registry'><p>Inspect versions, contracts, lifecycle, and candidate reviews.</p><form id='lane-registration'><label>Lane ID <input id='new-lane-id' required pattern='[A-Za-z0-9_\\-]+' /></label><label>Purpose <input id='new-lane-purpose' required /></label><button type='submit'>Register Lane</button><output id='registration-result' aria-live='polite'></output></form><button id='refresh-lanes' type='button'>Refresh lanes</button><div id='lanes' role='list'></div><pre id='lane-detail' aria-label='Lane detail'></pre><div id='lane-actions' aria-label='Lane lifecycle actions'><button id='enable-lane' type='button'>Enable</button><button id='disable-lane' type='button'>Disable</button><button id='retire-lane' type='button'>Retire</button><button id='supersede-lane' type='button'>Supersede</button><output id='lane-action-result' aria-live='polite'></output></div></section>
<section id='candidate-reviews' aria-label='Candidate reviews'><h2>Candidate reviews</h2><div id='reviews' role='list'></div></section>
<script>
async function loadLanes(){const r=await fetch('/api/lanes'); const d=await r.json(); const lanes=d.lanes||[]; document.querySelector('#lanes').textContent=JSON.stringify(lanes); if(lanes[0]) await inspectLane(lanes[0].lane_id, lanes[0].version);}
async function loadReviews(){const r=await fetch('/api/candidate-reviews'); const d=await r.json(); document.querySelector('#reviews').textContent=JSON.stringify(d.reviews||[]);}
let selectedLane=null; let bootstrapToken='';
async function registerLane(event){event.preventDefault(); const id=document.querySelector('#new-lane-id').value; const purpose=document.querySelector('#new-lane-purpose').value; const r=await fetch('/api/lanes',{method:'POST',headers:{'Content-Type':'application/json','X-Vesper-Bootstrap':bootstrapToken},body:JSON.stringify({lane_id:id,version:1,name:id,purpose,input_schema:{type:'object'},output_schema:{type:'object'}})}); document.querySelector('#registration-result').textContent=await r.text(); if(r.ok){event.target.reset(); await loadLanes();}}
async function inspectLane(id,version){selectedLane={id,version}; const [contract,history]=await Promise.all([fetch(`/api/lanes/${encodeURIComponent(id)}/${version}/contract`).then(r=>r.json()),fetch(`/api/lanes/${encodeURIComponent(id)}/history`).then(r=>r.json())]); document.querySelector('#lane-detail').textContent=JSON.stringify({contract,history},null,2);}
async function laneAction(path, body){if(!selectedLane){return;} const r=await fetch(`/api/lanes/${encodeURIComponent(selectedLane.id)}/${selectedLane.version}/${path}`,{method:'POST',headers:{'Content-Type':'application/json','X-Vesper-Bootstrap':window.vesperBootstrap||''},body:JSON.stringify(body||{})}); document.querySelector('#lane-action-result').textContent=await r.text(); await loadLanes();}
for(const [id,path,body] of [['enable-lane','enabled',{enabled:true}],['disable-lane','enabled',{enabled:false}],['retire-lane','retire',{}]]) document.querySelector(`#${id}`).addEventListener('click',()=>laneAction(path,body));
document.querySelector('#supersede-lane').addEventListener('click',()=>laneAction('supersede',{replacement_version:selectedLane ? selectedLane.version+1 : null}));
document.querySelector('#lane-registration').addEventListener('submit',registerLane);
document.querySelector('#refresh-lanes').addEventListener('click',()=>Promise.all([loadLanes(),loadReviews()]));
fetch('/api/bootstrap').then(r=>r.json()).then(d=>{bootstrapToken=d.session; window.vesperBootstrap=d.session; return Promise.all([loadLanes(),loadReviews()]);});
</script></main></body></html>""")


    @app.exception_handler(HTTPException)
    async def typed_http_exception(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "X-Vesper-Bootstrap", "X-Client-Request-ID"],
    )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.headers.get("host", "")
        if not (host.startswith("127.0.0.1") or host.startswith("localhost")):
            return JSONResponse({"detail": "loopback host required"}, status_code=400)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-vesper-bootstrap") != instance.bootstrap_token:
            return JSONResponse({"detail": "bootstrap session required"}, status_code=401)
        response = await call_next(request)
        nonce = secrets.token_urlsafe(18)
        if request.url.path in {"/dashboard", "/dashboard/lanes"} and response.headers.get("content-type", "").startswith("text/html"):
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            body = body.replace(b"<script>", f"<script nonce='{nonce}'>".encode("utf-8"))
            headers = dict(response.headers)
            headers.pop("content-length", None)
            response = HTMLResponse(content=body, status_code=response.status_code, headers=headers, media_type="text/html")
        response.headers["Content-Security-Policy"] = f"default-src 'self'; script-src 'nonce-{nonce}'; connect-src 'self' http://127.0.0.1 http://localhost"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "storage": "ready", "bind": "127.0.0.1"}

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, str]:
        return {"session": instance.bootstrap_token}

    def kernel_error(exc: KernelError) -> HTTPException:
        code = getattr(exc, "code", "KERNEL_ERROR")
        status = 410 if code == "CURSOR_EXPIRED" else 404 if code == "PROCESS_NOT_FOUND" else 409
        return HTTPException(status_code=status, detail={"error": {"code": code, "message": str(exc), "retryable": bool(getattr(exc, "retryable", False))}})

    @app.post("/api/processes")
    async def create_process(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            process = instance.kernel.submit(
                str(body.get("origin", "director")), volatile=bool(body.get("volatile", False)),
                client_request_id=client_request_id, authority=body.get("authority"),
                delegable_authority=body.get("delegable_authority"), priority=body.get("priority", "NORMAL"),
            )
        except KernelError as exc:
            raise kernel_error(exc) from exc
        return {"ok": True, "result": {"process_id": process.process_id, "process": process.__dict__}, "process": process.__dict__}

    @app.get("/api/candidate-reviews")
    def list_candidate_reviews():
        return {"reviews": [review_payload(item) for item in instance.candidate_reviews.list()]}

    @app.get("/api/lanes")
    def list_lanes(lane_id: str | None = None):
        return {"lanes": [item.__dict__ for item in instance.lanes.list(lane_id)]}

    @app.post("/api/lanes")
    async def register_lane(request: Request):
        """Register a Lane through the authenticated local control boundary.

        Registration is intentionally separate from activation: callers must
        explicitly use the existing enabled lifecycle endpoint after review.
        """
        body = await request.json()
        allowed = {
            "lane_id", "version", "name", "purpose", "input_schema", "output_schema",
            "context_policy", "tool_profile", "permission_ceiling",
            "capability_requirements", "model_policy", "escalation_policy",
            "stop_conditions", "evaluation_contract",
        }
        unknown = set(body) - allowed
        if unknown:
            raise HTTPException(status_code=422, detail={"error": {"code": "LANE_INVALID", "message": "unknown Lane fields"}})
        try:
            definition = LaneDefinition(
                lane_id=str(body["lane_id"]), version=int(body["version"]),
                name=str(body.get("name", body["lane_id"])), purpose=str(body["purpose"]),
                input_schema=dict(body["input_schema"]), output_schema=dict(body["output_schema"]),
                context_policy=dict(body.get("context_policy", {})), tool_profile=dict(body.get("tool_profile", {})),
                permission_ceiling=dict(body.get("permission_ceiling", {})),
                capability_requirements=dict(body.get("capability_requirements", {})),
                model_policy=dict(body.get("model_policy", {})),
                escalation_policy=dict(body.get("escalation_policy", {})),
                stop_conditions=dict(body.get("stop_conditions", {})),
                evaluation_contract=dict(body.get("evaluation_contract", {})), enabled=False,
            )
            lane = instance.lanes.register(definition)
            return {"lane": lane.__dict__}
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail={"error": {"code": "LANE_INVALID", "message": str(exc)}}) from exc
        except LaneError as exc:
            raise HTTPException(status_code=409, detail={"error": {"code": exc.code, "message": str(exc)}}) from exc

    @app.get("/api/lanes/{lane_id}/history")
    def lane_history(lane_id: str):
        return {"lanes": [item.__dict__ for item in instance.lanes.list(lane_id)]}

    @app.get("/api/lanes/{lane_id}/{version}/contract")
    def lane_contract(lane_id: str, version: int):
        try:
            lane = instance.lanes.get(lane_id, version)
            return {"lane_id": lane.lane_id, "version": lane.version, "contract": {
                "input_schema": lane.input_schema, "output_schema": lane.output_schema,
                "context_policy": lane.context_policy, "tool_profile": lane.tool_profile,
                "permission_ceiling": lane.permission_ceiling, "model_policy": lane.model_policy,
                "evaluation_contract": lane.evaluation_contract,
            }}
        except LaneError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": exc.code, "message": str(exc)}}) from exc

    @app.get("/api/lanes/{lane_id}/latest")
    def latest_lane(lane_id: str):
        try:
            return {"lane": instance.lanes.latest(lane_id).__dict__}
        except LaneError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": exc.code, "message": str(exc)}}) from exc

    @app.get("/api/lanes/{lane_id}/{version}")
    def get_lane(lane_id: str, version: int):
        try:
            return {"lane": instance.lanes.get(lane_id, version).__dict__}
        except LaneError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": exc.code, "message": str(exc)}}) from exc

    @app.post("/api/lanes/{lane_id}/{version}/enabled")
    async def set_lane_enabled(lane_id: str, version: int, request: Request):
        body = await request.json()
        try:
            lane = instance.lanes.set_enabled(lane_id, version, bool(body["enabled"]))
            return {"lane": lane.__dict__}
        except LaneError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": exc.code, "message": str(exc)}}) from exc

    @app.post("/api/lanes/{lane_id}/{version}/retire")
    def retire_lane(lane_id: str, version: int):
        try:
            return {"lane": instance.lanes.retire(lane_id, version).__dict__}
        except LaneError as exc:
            raise HTTPException(status_code=409, detail={"error": {"code": exc.code, "message": str(exc)}}) from exc

    @app.post("/api/lanes/{lane_id}/{version}/supersede")
    async def supersede_lane(lane_id: str, version: int, request: Request):
        body = await request.json()
        try:
            replacement = int(body["replacement_version"])
            return {"lane": instance.lanes.supersede(lane_id, version, replacement).__dict__}
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="replacement_version is required") from exc
        except LaneError as exc:
            raise HTTPException(status_code=409, detail={"error": {"code": exc.code, "message": str(exc)}}) from exc

    @app.get("/api/lane-invocations/{invocation_id}")
    def get_lane_invocation(invocation_id: str):
        try:
            return {"invocation": instance.lane_invocations.get(invocation_id).__dict__}
        except LaneInvocationError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": exc.code, "message": str(exc)}}) from exc

    @app.get("/api/processes/{process_id}/lane-invocations")
    def list_process_lane_invocations(process_id: str):
        return {"invocations": [item.__dict__ for item in instance.lane_invocations.list(process_id)]}

    @app.get("/api/processes")
    def list_processes():
        snapshot = instance.kernel.snapshot()
        processes = snapshot.get("processes", [])
        effects = snapshot.get("effects", [])
        effect_by_process = {str(effect.get("process_id")): effect for effect in effects}
        projection = []
        for process in processes:
            item = dict(process)
            effect = effect_by_process.get(str(item.get("process_id")))
            item["waiting_reason"] = "approval_required" if item.get("status") == "WAITING" else None
            item["parent_id"] = item.get("parent_process_id")
            item["children"] = [child.get("process_id") for child in processes if child.get("parent_process_id") == item.get("process_id")]
            item["dependency_state"] = "none"
            item["result_summary"] = (effect or {}).get("status")
            item["effect_summary"] = (effect or {}).get("output", {})
            projection.append(item)
        return {"processes": projection}

    @app.get("/api/processes/{process_id}")
    def get_process(process_id: str):
        process = instance.kernel.get(process_id)
        if process is None:
            raise HTTPException(status_code=404, detail="process not found")
        return {"process": process.__dict__}

    @app.post("/api/processes/{process_id}/transition")
    async def transition_process(process_id: str, request: Request):
        body = await request.json()
        try:
            process = instance.kernel.transition(process_id, ProcessStatus(str(body["status"])), expected_revision=body.get("expected_revision"))
        except KernelError as exc:
            raise kernel_error(exc) from exc
        return {"ok": True, "result": {"process": process.__dict__}}

    @app.get("/api/watch")
    def watch(cursor: int = 0):
        try:
            return {"ok": True, **instance.kernel.events_after(cursor)}
        except KernelError as exc:
            raise kernel_error(exc) from exc

    @app.get("/api/snapshot")
    def snapshot():
        return instance.kernel.snapshot()

    @app.get("/api/dashboard/today")
    def dashboard_today() -> dict[str, object]:
        snapshot = instance.kernel.snapshot()
        effects = instance.storage.write(lambda c: [dict(r) for r in c.execute("SELECT * FROM effects ORDER BY created_at, effect_id").fetchall()])
        approvals = instance.storage.write(lambda c: [dict(r) for r in c.execute("SELECT * FROM approvals ORDER BY created_at, approval_id").fetchall()])
        return {
            "processes": snapshot.get("processes", []),
            "lanes": [item.__dict__ for item in instance.lanes.list()],
            "approvals": approvals,
            "effects": effects,
            "memory": {"available": True},
            "observability": {
                "process_count": len(snapshot.get("processes", [])),
                "effect_count": len(effects),
                "approval_count": len(approvals),
                "event_cursor": snapshot.get("cursor", 0),
                "verification": {"source": "kernel_snapshot", "status": "available"},
            },
        }

    @app.get("/api/diagnostics/export")
    def diagnostic_export() -> dict[str, object]:
        snapshot = instance.kernel.snapshot()
        events = instance.kernel.events_after(0).get("events", [])
        return {
            "processes": snapshot.get("processes", []),
            "effects": instance.storage.write(lambda c: [dict(r) for r in c.execute("SELECT * FROM effects ORDER BY created_at, effect_id").fetchall()]),
            "events": events,
            "lanes": [item.__dict__ for item in instance.lanes.list()],
            "recovery": {"cursor": snapshot.get("cursor", 0), "event_count": len(events)},
        }

    @app.post("/api/data/export")
    async def safe_data_export(request: Request):
        body = await request.json()
        destination = Path(str(body.get("destination", ""))).expanduser()
        if not destination.is_absolute():
            raise HTTPException(status_code=422, detail={"code": "ABSOLUTE_DESTINATION_REQUIRED", "message": "destination must be absolute"})
        if instance.connections.artifacts is None:
            raise HTTPException(status_code=503, detail={"code": "ARTIFACT_STORE_UNAVAILABLE", "message": "artifact store is unavailable"})
        return instance.connections.artifacts.safe_export(destination, artifact_ids=body.get("artifact_ids"))

    @app.get("/api/effects")
    def list_effects():
        def read(conn):
            return [dict(row) for row in conn.execute("SELECT * FROM effects ORDER BY created_at, effect_id").fetchall()]
        return {"effects": instance.storage.write(read)}

    @app.post("/api/memories")
    async def create_memory(request: Request):
        body = await request.json()
        memory = instance.memory.put(kind=str(body["kind"]), payload=dict(body["payload"]), schema_id=str(body.get("schema_id", "memory")), scope_refs=tuple(body.get("scope_refs", [])), provenance=dict(body.get("provenance", {"source": "director"})), memory_id=body.get("memory_id"))
        return {"memory": instance.memory.to_dict(memory)}

    @app.get("/api/memories")
    def list_memories():
        return {"memories": [instance.memory.to_dict(item) for item in instance.memory.latest()]}

    @app.get("/api/memories/{memory_id}")
    def get_memory(memory_id: str):
        memory = instance.memory.get(memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="memory not found")
        return {"memory": instance.memory.to_dict(memory), "history": [instance.memory.to_dict(item) for item in instance.memory.history(memory_id)]}

    @app.get("/api/memory/search")
    def search_memory(q: str, scope: str | None = None):
        result = instance.memory.retrieve(q, scope_refs=(scope,) if scope else ())
        return {"status": result.status, "query": result.query, "items": [instance.memory.to_dict(item) for item in result.items]}

    @app.post("/api/context-pack")
    async def context_pack(request: Request):
        body = await request.json()
        pack = ContextPack.build(dict(body.get("frames", {})), fault=body.get("fault"))
        return {"pack_id": pack.pack_id, "serialized": pack.serialize(), "wire_prefix": pack.wire_prefix()}

    @app.post("/api/director/submit")
    async def director_submit(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        request_id = client_request_id or str(body.get("client_request_id") or secrets.token_urlsafe(18))
        prompt = str(body.get("input", body.get("prompt", ""))).strip()
        if not prompt:
            raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT", "message": "input is required"})
        try:
            return instance.submit_director(prompt, body.get("conversation_id"), request_id, principal=str(body.get("principal", "director")))
        except RuntimeConfigurationError as exc:
            raise HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.post("/api/model/invoke")
    async def invoke_model(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        """Deprecated thin adapter; execution authority is director.submit."""
        body = await request.json()
        body["input"] = body.get("input", body.get("prompt", "Reply with exactly: VESPER_READY"))
        request_id = client_request_id or body.get("client_request_id")
        if request_id:
            body["client_request_id"] = request_id
        class _Request:
            async def json(self): return body
        try:
            return await director_submit(_Request(), client_request_id=request_id)  # type: ignore[arg-type]
        except RuntimeConfigurationError as exc:
            raise HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.get("/api/conversations")
    def list_conversations():
        return {"conversations": instance.conversations.list()}

    @app.post("/api/conversations")
    async def create_conversation(request: Request):
        body = await request.json()
        process_id = str(body.get("process_id") or instance.kernel.submit("director", volatile=False).process_id)
        return {"conversation": instance.conversations.create(process_id)}

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str):
        conversation = instance.conversations.get(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {"conversation": conversation, "messages": instance.conversations.messages(conversation_id)}

    @app.post("/api/model/route")
    async def model_route(request: Request):
        body = await request.json()
        route = instance.models.route(CognitiveRequest(capabilities=frozenset(body.get("capabilities", ["text"])), privacy=str(body.get("privacy", "local_preferred")), reliability_floor=float(body.get("reliability_floor", 0.0)), max_cost=body.get("max_cost"), max_latency_ms=body.get("max_latency_ms")))
        return {"route_id": route.route_id, "model_id": route.model_id, "provider": route.provider}

    @app.post("/api/processes/{process_id}/syscalls")
    async def execute_syscall(process_id: str, request: Request):
        body = await request.json()
        syscall = SyscallRequest(process_id=process_id, operation=str(body["operation"]), target=str(body.get("target", "*")), args=dict(body.get("args", {})), precondition=dict(body.get("precondition", {})), actor="model")
        try:
            result = instance.syscalls.execute(syscall, approval_id=body.get("approval_id"))
        except SyscallError as exc:
            if getattr(exc, "code", "") == "APPROVAL_REQUIRED":
                approval_id = instance.syscalls.request_approval(syscall)
                return {"status": "WAITING", "approval_id": approval_id}
            raise HTTPException(status_code=403, detail={"code": getattr(exc, "code", "SYSCALL_ERROR"), "message": str(exc)}) from exc
        return {"status": result.status, "output": result.output, "effect_id": result.effect_id, "approval_id": result.approval_id}

    @app.get("/api/approvals")
    def list_approvals():
        def read(conn):
            return [dict(row) for row in conn.execute("SELECT * FROM approvals ORDER BY created_at, approval_id").fetchall()]
        return {"approvals": instance.storage.write(read)}

    @app.post("/api/approvals/{approval_id}")
    async def decide_approval(approval_id: str, request: Request):
        body = await request.json()
        try:
            decision = ApprovalDecision(str(body["decision"]))
            approval = instance.syscalls.decide(approval_id, decision)
        except SyscallError as exc:
            raise HTTPException(status_code=409, detail={"code": getattr(exc, "code", "SYSCALL_ERROR"), "message": str(exc)}) from exc
        return {"approval_id": approval, "decision": decision}

    @app.post("/api/effects/{effect_id}/reconcile")
    async def reconcile_effect(effect_id: str, request: Request):
        body = await request.json()
        try:
            instance.syscalls.reconcile(effect_id, status=EffectStatus(str(body["status"])), output=dict(body.get("output", {})))
        except SyscallError as exc:
            raise HTTPException(status_code=409, detail={"code": getattr(exc, "code", "SYSCALL_ERROR"), "message": str(exc)}) from exc
        return {"effect_id": effect_id, "status": body["status"]}

    def core_error(exc: CoreAppError) -> HTTPException:
        code = getattr(exc, "code", "CORE_APP_ERROR")
        status = 409 if code in {"REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT"} else 404 if code == "NOT_FOUND" else 422
        return HTTPException(status_code=status, detail={"code": code, "message": str(exc), "retryable": code == "REVISION_CONFLICT"})

    @app.get("/api/projects")
    def list_projects():
        return {"projects": instance.core_apps.list_projects()}

    @app.post("/api/projects")
    async def create_project(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            return {"project": instance.core_apps.create_project(str(body["name"]), str(body.get("objective", "")), client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    @app.patch("/api/projects/{project_id}")
    async def update_project(project_id: str, request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            return {"project": instance.core_apps.update_project(project_id, dict(body.get("patch", body)), body.get("expected_revision"), client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    @app.get("/api/tasks")
    def list_tasks(status: str | None = None):
        return {"tasks": instance.core_apps.list_tasks(status)}

    @app.post("/api/tasks")
    async def create_task(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            return {"task": instance.core_apps.create_task(str(body["title"]), int(body.get("priority", 3)), body.get("project_id"), body.get("due_at"), client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            return {"task": instance.core_apps.update_task(task_id, dict(body.get("patch", body)), body.get("expected_revision"), client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    @app.get("/api/calendar")
    def list_calendar():
        return {"calendar": instance.core_apps.list_calendar()}

    @app.get("/api/ideas")
    def list_ideas():
        return {"ideas": instance.core_apps.list_ideas()}

    @app.post("/api/calendar")
    async def create_calendar(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            return {"calendar": instance.core_apps.create_calendar(str(body["title"]), str(body["starts_at"]), str(body["ends_at"]), body.get("project_id"), client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    @app.patch("/api/calendar/{calendar_id}")
    async def update_calendar(calendar_id: str, request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            return {"calendar": instance.core_apps.update_calendar(calendar_id, dict(body.get("patch", body)), body.get("expected_revision"), client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    @app.post("/api/ideas")
    async def capture_idea(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            return {"idea": instance.core_apps.capture_idea(dict(body.get("payload", body)), client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    @app.post("/api/calendar/{calendar_id}/undo")
    async def undo_calendar(calendar_id: str, request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        try:
            return {"calendar": instance.core_apps.undo_calendar(calendar_id, client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    @app.get("/api/settings")
    def settings():
        result = instance.core_apps.settings()
        result["model_route"] = result.get("model_route", {"status": "unconfigured"})
        result["web_research"] = {"status": "available" if instance.connections.list_capability_stats().get("authorized", 0) else "unconfigured"}
        return result

    @app.get("/api/first-boot")
    def first_boot_status():
        settings = instance.core_apps.settings()
        return {
            "first_boot_completed": bool(settings.get("first_boot_completed", False)),
            "director_display_name": settings.get("director_display_name"),
            "model_route": settings.get("model_route", {"status": "unconfigured"}),
        }

    @app.post("/api/first-boot/connection")
    async def first_boot_connection(request: Request):
        body = await request.json()
        provider = str(body.get("provider", "custom"))
        display_name = str(body.get("display_name", provider)).strip()
        base_url = str(body.get("base_url", "")).strip().rstrip("/")
        api_style = str(body.get("api_style", "official"))
        model_id = str(body.get("model_id", "")).strip()
        credential = body.get("credential")
        if not display_name or not base_url:
            raise HTTPException(status_code=422, detail={"code": "INVALID_CONNECTION", "message": "A display name and endpoint URL are required."})
        if credential is not None and not isinstance(credential, str):
            raise HTTPException(status_code=422, detail={"code": "INVALID_CREDENTIAL", "message": "Credential must be text."})
        endpoint_type = "local" if provider == "local" or api_style == "local-compatible" else "custom"
        credential_ref = None
        try:
            if credential:
                credential_ref = instance.secret_store.put(credential, label=provider)
            connection = ProviderConnection("pending", provider, base_url, model_id, api_style, credential_ref, endpoint_type)
            result = ProviderAdapter(connection, instance.secret_store).validate_and_invoke()
            if result.status != "MODEL_READY":
                raise HTTPException(status_code=422, detail={"code": "CONNECTION_VALIDATION_FAILED", "message": "Vesper could not validate this connection. Check the endpoint, model, and credential, then try again."})
        except HTTPException:
            if credential_ref:
                instance.secret_store.delete(credential_ref)
            raise
        except Exception as exc:
            if credential_ref:
                instance.secret_store.delete(credential_ref)
            raise HTTPException(status_code=422, detail={"code": "CONNECTION_VALIDATION_FAILED", "message": "Vesper could not validate this connection. Check the endpoint, model, and credential, then try again."}) from exc
        connection_id = f"{provider}-{secrets.token_hex(6)}"
        try:
            connection = instance.connections.register_provider_connection(connection_id=connection_id, display_name=display_name, base_url=base_url, api_style=api_style, credential_ref=credential_ref, endpoint_type=endpoint_type, provider=provider)
        except ConnectionError as exc:
            raise connection_error(exc) from exc
        return {"connection": {"connection_id": connection["connection_id"], "display_name": connection["display_name"], "base_url": connection["base_url"], "api_style": connection["api_style"], "has_credential": bool(credential_ref)}, "models": [model_id] if model_id else []}

    @app.post("/api/first-boot/complete")
    async def complete_first_boot(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        director_display_name = str(body.get("director_display_name", "")).strip()
        if not director_display_name:
            raise HTTPException(status_code=422, detail={"code": "DIRECTOR_NAME_REQUIRED", "message": "Director display name is required."})
        model_route = body.get("model_route", {"status": "unconfigured"})
        if not isinstance(model_route, dict):
            raise HTTPException(status_code=422, detail={"code": "INVALID_MODEL_ROUTE", "message": "Default model is invalid."})
        if model_route.get("status") == "configured":
            connection_id = str(model_route.get("connection_id", ""))
            row = instance.storage.write(lambda c: c.execute("SELECT * FROM provider_connections WHERE connection_id=?", (connection_id,)).fetchone())
            if row is None:
                raise HTTPException(status_code=422, detail={"code": "INVALID_MODEL_ROUTE", "message": "The selected provider connection is unavailable."})
            route = ModelRoute(
                route_id="default-runtime",
                model_id=str(model_route.get("model_id", "")),
                provider=str(row["provider"] or model_route.get("provider", "custom")),
                capabilities=frozenset({"text"}), privacy="local" if model_route.get("endpoint_type") == "local" else "remote",
                reliability=0.9, cost=0.0, latency_ms=1000.0, enabled=True,
                credential_ref=row["credential_ref"], base_url=row["base_url"], connection_id=connection_id,
                api_style=row["api_style"], endpoint_type=model_route.get("endpoint_type", "custom"),
                max_output_tokens=model_route.get("max_output_tokens"),
            )
            instance.models.register(route)
            model_route = {"status": "configured", "route_id": route.route_id, "connection_id": connection_id, "model_id": route.model_id, "provider": route.provider}
        settings = instance.core_apps.update_settings({"director_display_name": director_display_name, "model_route": model_route, "first_boot_completed": True}, client_request_id)
        return {"settings": settings}

    @app.post("/api/settings")
    async def update_settings(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            return {"settings": instance.core_apps.update_settings(dict(body.get("patch", body)), client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    @app.get("/api/search")
    def deterministic_search(q: str):
        return instance.core_apps.search(q)

    @app.post("/api/anchors")
    async def create_anchor(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        resource_ref = dict(body.get("resource_ref", {}))
        if not resource_ref and body.get("resource_type") and body.get("resource_id"):
            resource_ref = {"resource_type": str(body["resource_type"]), "resource_id": str(body["resource_id"])}
        if not resource_ref:
            raise HTTPException(status_code=422, detail="resource_ref is required")
        try:
            return {"anchor": instance.core_apps.create_anchor(str(body.get("anchor_type", "resource")), resource_ref, list(body.get("selection_refs", [])), body.get("view_scope_ref"), client_request_id)}
        except CoreAppError as exc:
            raise core_error(exc) from exc

    def connection_error(exc: ConnectionError) -> HTTPException:
        code = getattr(exc, "code", "CONNECTION_ERROR")
        status = 404 if code in {"CAPABILITY_NOT_FOUND", "EVIDENCE_NOT_FOUND"} else 422
        return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})

    @app.post("/api/capabilities")
    async def register_capability(request: Request):
        body = await request.json()
        try:
            return {"capability": instance.connections.register_capability(server_id=str(body["server_id"]), name=str(body["name"]), description=str(body.get("description", "")), schema=dict(body.get("schema", {})), risk_class=str(body.get("risk_class", "UNTRUSTED")))}
        except ConnectionError as exc:
            raise connection_error(exc) from exc

    @app.post("/api/mcp/local-sandbox")
    async def register_local_mcp_sandbox(request: Request):
        body = await request.json()
        try:
            server_id = str(body.get("server_id", "local-custom-sandbox"))
            return {"server": instance.mcp_gateway.register_local_server(server_id=server_id, display_name=str(body.get("display_name", "Local Custom MCP Sandbox")), transport=LocalCustomMCPSandbox())}
        except ConnectionError as exc:
            raise connection_error(exc) from exc

    @app.post("/api/mcp/{server_id}/discover")
    def discover_mcp(server_id: str):
        try:
            return {"capabilities": instance.mcp_gateway.discover(server_id)}
        except ConnectionError as exc:
            raise connection_error(exc) from exc

    @app.get("/api/mcp/overview")
    def mcp_overview():
        return instance.mcp_gateway.overview()

    @app.post("/api/mcp/{server_id}/read")
    async def mcp_read(server_id: str, request: Request):
        body = await request.json()
        try:
            return {"observation": instance.mcp_gateway.read(server_id=server_id, capability_id=str(body["capability_id"]), arguments=dict(body.get("arguments", {})))}
        except ConnectionError as exc:
            raise connection_error(exc) from exc

    @app.post("/api/mcp/{server_id}/effects")
    async def propose_mcp_effect(server_id: str, request: Request):
        body = await request.json()
        try:
            return {"effect": instance.mcp_gateway.propose_write(server_id=server_id, capability_id=str(body["capability_id"]), process_id=str(body["process_id"]), idempotency_key=str(body["idempotency_key"]))}
        except ConnectionError as exc:
            raise connection_error(exc) from exc

    @app.post("/api/mcp/effects/{effect_id}/approval")
    async def approve_mcp_effect(effect_id: str, request: Request):
        body = await request.json()
        try:
            return {"effect": instance.mcp_gateway.approve_and_execute(effect_id=effect_id, approved=bool(body.get("approved", False)), arguments=dict(body.get("arguments", {})))}
        except ConnectionError as exc:
            raise connection_error(exc) from exc

    @app.get("/api/connections")
    def list_connections():
        capabilities = instance.connections.search_capabilities("", limit=20)
        return {
            "connections": [
                {
                    "provider": item["server_id"],
                    "name": item["name"],
                    "description": item["description"],
                    "health": "available" if item["state"] in {"EXPOSED", "AUTHORIZED"} else "unconfigured",
                    "status": item["state"],
                    "risk_class": item["risk_class"],
                }
                for item in capabilities
            ],
            "stats": instance.connections.list_capability_stats(),
            "provider_connections": instance.connections.provider_connections(),
        }

    @app.get("/api/capabilities/search")
    def search_capabilities(q: str = "", limit: int = 20):
        return {"capabilities": instance.connections.search_capabilities(q, limit=limit), "stats": instance.connections.list_capability_stats()}

    @app.post("/api/capabilities/page")
    async def page_capabilities(request: Request):
        body = await request.json()
        try:
            return {"capabilities": instance.connections.page_capabilities(list(body.get("capability_ids", [])))}
        except ConnectionError as exc:
            raise connection_error(exc) from exc

    @app.post("/api/connections/secrets/metadata")
    async def register_secret_metadata(request: Request):
        body = await request.json()
        try:
            return {"secret": instance.connections.register_secret_metadata(provider=str(body["provider"]), label=str(body.get("label", "")), secret_ref=str(body["secret_ref"]))}
        except ConnectionError as exc:
            raise connection_error(exc) from exc

    @app.get("/api/connections/secrets/metadata")
    def list_secret_metadata():
        return {"secrets": instance.connections.list_secret_metadata()}

    @app.post("/api/web/evidence")
    async def fetch_web_evidence(request: Request):
        body = await request.json()
        try:
            return {"evidence": instance.connections.fetch_evidence(str(body["url"]), query=body.get("query"), max_bytes=int(body.get("max_bytes", 1_000_000)))}
        except ConnectionError as exc:
            raise connection_error(exc) from exc

    @app.get("/api/web/evidence/{evidence_id}")
    def get_web_evidence(evidence_id: str):
        evidence = instance.connections.get_evidence(evidence_id)
        if evidence is None:
            raise HTTPException(status_code=404, detail={"code": "EVIDENCE_NOT_FOUND", "message": "evidence not found"})
        return {"evidence": evidence}

    @app.get("/api/director")
    def director():
        row = instance.storage.write(lambda conn: conn.execute("SELECT preferred_name FROM director_profile WHERE id = 1").fetchone())
        return {"preferred_name": row["preferred_name"] if row else None}

    @app.post("/api/director")
    async def update_director(request: Request):
        body = await request.json()
        preferred_name = body.get("preferred_name")
        if preferred_name is not None and not isinstance(preferred_name, str):
            raise HTTPException(status_code=422, detail="preferred_name must be a string or null")
        instance.storage.write(
            lambda conn: conn.execute(
                "INSERT INTO director_profile(id, preferred_name) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET preferred_name=excluded.preferred_name, updated_at=CURRENT_TIMESTAMP",
                (preferred_name,),
            )
        )
        return {"preferred_name": preferred_name}

    frontend = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend.exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets") if (frontend / "assets").exists() else None

        @app.get("/")
        def index():
            return FileResponse(frontend / "index.html")

    return app
