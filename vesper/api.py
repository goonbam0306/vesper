"""Loopback System API bootstrap subset."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ensure_runtime_dirs, vesper_home
from .storage import Storage
from .kernel import Kernel, KernelError, ProcessStatus
from .memory import MemoryStore
from .context import ContextPack
from .model_runtime import ModelRegistry, CognitiveRequest


class Runtime:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or vesper_home()
        ensure_runtime_dirs(self.home)
        self.storage = Storage(self.home / "vesper.sqlite3")
        self.kernel = Kernel(self.storage)
        self.memory = MemoryStore(self.storage)
        self.models = ModelRegistry(self.storage)
        self.bootstrap_token = secrets.token_urlsafe(32)

    def start(self) -> None:
        self.storage.migrate()
        self.storage.start()

    def stop(self) -> None:
        self.storage.stop()



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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Vesper-Bootstrap"],
    )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.headers.get("host", "")
        if not (host.startswith("127.0.0.1") or host.startswith("localhost")):
            return JSONResponse({"detail": "loopback host required"}, status_code=400)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-vesper-bootstrap") != instance.bootstrap_token:
            return JSONResponse({"detail": "bootstrap session required"}, status_code=401)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self' http://127.0.0.1 http://localhost"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "storage": "ready", "bind": "127.0.0.1"}

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, str]:
        return {"session": instance.bootstrap_token}

    @app.post("/api/processes")
    async def create_process(request: Request, client_request_id: str | None = Header(default=None, alias="X-Client-Request-ID")):
        body = await request.json()
        try:
            process = instance.kernel.submit(str(body.get("origin", "director")), volatile=bool(body.get("volatile", False)), client_request_id=client_request_id)
        except KernelError as exc:
            raise HTTPException(status_code=409, detail={"code": getattr(exc, "code", "KERNEL_ERROR"), "message": str(exc)}) from exc
        return {"process": process.__dict__}

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
            raise HTTPException(status_code=409, detail={"code": getattr(exc, "code", "KERNEL_ERROR"), "message": str(exc)}) from exc
        return {"process": process.__dict__}

    @app.get("/api/watch")
    def watch(cursor: int = 0):
        return {"events": instance.kernel.events_after(cursor), "cursor": instance.kernel.snapshot()["cursor"]}

    @app.get("/api/snapshot")
    def snapshot():
        return instance.kernel.snapshot()

    @app.post("/api/memories")
    async def create_memory(request: Request):
        body = await request.json()
        memory = instance.memory.put(kind=str(body["kind"]), payload=dict(body["payload"]), schema_id=str(body.get("schema_id", "memory")), scope_refs=tuple(body.get("scope_refs", [])), provenance=dict(body.get("provenance", {"source": "director"})), memory_id=body.get("memory_id"))
        return {"memory": instance.memory.to_dict(memory)}

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

    @app.post("/api/model/route")
    async def model_route(request: Request):
        body = await request.json()
        route = instance.models.route(CognitiveRequest(capabilities=frozenset(body.get("capabilities", ["text"])), privacy=str(body.get("privacy", "local_preferred")), reliability_floor=float(body.get("reliability_floor", 0.0)), max_cost=body.get("max_cost"), max_latency_ms=body.get("max_latency_ms")))
        return {"route_id": route.route_id, "model_id": route.model_id, "provider": route.provider}

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
