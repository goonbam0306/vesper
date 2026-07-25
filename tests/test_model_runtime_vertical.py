import json
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from vesper.model_runtime import ModelRoute, ProviderAdapters
from vesper.api import Runtime
from vesper.model_runtime import CognitiveRequest, ProviderResponse
from vesper.provider_adapter import ProviderAdapter, ProviderConnection
from vesper.secret_store import EphemeralTestSecretStore


MODEL = "vesper-test-model"
SECRET = "vertical-secret-marker-7f2c"


class FakeProviderHandler(BaseHTTPRequestHandler):
    requests = []
    expected_secret = SECRET

    def log_message(self, *_args):
        return

    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        encoded = json.dumps({"data": [{"id": MODEL, "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if self.headers.get("Authorization") != f"Bearer {self.expected_secret}":
            self.send_error(401, "unauthorized")
            return
        if body.get("model") != MODEL:
            self.send_error(404, "wrong model")
            return
        response = {"id": "fake-request", "choices": [{"message": {"content": "VESPER_READY"}}], "usage": {"prompt_tokens": 4, "completion_tokens": 1}}
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@pytest.fixture
def fake_provider():
    FakeProviderHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class Pack:
    def serialize(self):
        return "Reply exactly: VESPER_READY"


def make_route(base_url, ref):
    return ModelRoute(
        route_id="route-vertical", model_id=MODEL, provider="local",
        capabilities=frozenset({"text"}), privacy="local", reliability=1.0,
        cost=0.0, latency_ms=1000.0, enabled=True, credential_ref=ref,
        base_url=base_url, connection_id="connection-vertical",
        api_style="openai-compatible", endpoint_type="local", max_output_tokens=None,
    )


def test_provider_adapter_uses_secret_store_and_real_socket(fake_provider):
    _server, base_url = fake_provider
    store = EphemeralTestSecretStore()
    ref = store.put(SECRET, label="local")
    route = make_route(base_url, ref)

    result = ProviderAdapters(store).invoke(route, Pack())

    assert result.output == "VESPER_READY"
    assert result.error is None
    request = FakeProviderHandler.requests[-1]
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert request["body"]["model"] == MODEL
    assert SECRET not in route.__repr__()


@pytest.mark.parametrize("payload, expected", [
    ({"choices": [{"message": {"content": [{"type": "text", "text": "PART_A"}, {"type": "text", "text": "PART_B"}]}}]}, "PART_APART_B"),
    ({"output": [{"type": "message", "content": [{"type": "output_text", "text": "RESPONSES_STYLE"}]}]}, "RESPONSES_STYLE"),
    ({"output_text": "OUTPUT_TEXT"}, "OUTPUT_TEXT"),
])
def test_provider_adapter_normalizes_observed_text_shapes(payload, expected):
    assert ProviderAdapter._extract_output(payload) == expected


def test_provider_adapter_classifies_empty_and_malformed_shapes():
    connection = ProviderConnection("c", "local", "http://127.0.0.1:1", MODEL, "openai-compatible", None, "local")
    adapter = ProviderAdapter(connection, EphemeralTestSecretStore())
    with pytest.raises(Exception) as empty:
        adapter._result_from_payload({"choices": [{"message": {"content": ""}}]})
    assert getattr(empty.value, "code", None) == "MODEL_EMPTY_OUTPUT"
    with pytest.raises(Exception) as malformed:
        adapter._result_from_payload({"unexpected": {"value": True}})
    assert getattr(malformed.value, "code", None) == "PROVIDER_RESPONSE_MALFORMED"


def test_openai_compatible_payload_without_budget_has_no_arbitrary_token_limit():
    connection = ProviderConnection("c", "local", "http://127.0.0.1:1", MODEL, "openai-compatible", None, "local")
    payload = ProviderAdapter(connection, EphemeralTestSecretStore())._generation_payload("x")
    assert payload == {"model": MODEL, "messages": [{"role": "user", "content": "x"}]}


def test_openai_compatible_payload_maps_configured_budget():
    connection = ProviderConnection("c", "local", "http://127.0.0.1:1", MODEL, "openai-compatible", None, "local")
    payload = ProviderAdapter(connection, EphemeralTestSecretStore())._generation_payload("x", max_output_tokens=64)
    assert payload == {"model": MODEL, "max_tokens": 64, "messages": [{"role": "user", "content": "x"}]}


def test_provider_wire_prompt_contains_k0_identity_and_lower_context(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    captured = {}
    runtime.models.register(ModelRoute("wire", MODEL, "capture", frozenset({"text"}), "local", .9, 0, 10, True, None, "http://127.0.0.1:1", "c", "openai-compatible", "local"))
    runtime.providers.register("capture", lambda route, pack: (captured.update({"pack": pack}), ProviderResponse("Vesper answer"))[1])
    process = runtime.kernel.submit("director", volatile=False)
    runtime.kernel.run_scheduler()
    result = runtime.cognitive.invoke_model(process.process_id, CognitiveRequest(privacy="local_only"), {"prompt": "hello"}, route=runtime.models.route(CognitiveRequest(privacy="local_only")))
    assert result.success
    assert captured["pack"].frames["K0"]["identity"].startswith("You are Vesper")
    runtime.stop()


def test_model_route_budget_is_optional_and_round_trips_when_schema_has_column(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.start()
    route = ModelRoute("budget-route", MODEL, "local", frozenset({"text"}), "local", 1.0, 0, 1, True, None, max_output_tokens=64)
    runtime.models.register(route)
    loaded = runtime.models._row(runtime.storage.write(lambda c: c.execute("SELECT * FROM model_routes WHERE route_id=?", (route.route_id,)).fetchone()))
    assert loaded.max_output_tokens == 64


def test_legacy_route_without_budget_remains_none():
    route = ModelRoute("legacy", MODEL, "local", frozenset({"text"}), "local", 1.0, 0, 1, True, None)
    assert route.max_output_tokens is None


def test_model_route_budget_maps_to_provider_adapter(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.start()
    route = ModelRoute("budget-route", MODEL, "local", frozenset({"text"}), "local", 1.0, 0, 1, True, None, max_output_tokens=64)
    runtime.models.register(route)
    runtime.providers.register("local", lambda *_: ProviderResponse("ok"))
    assert route.max_output_tokens == 64


def test_reasoning_capable_fake_endpoint_returns_non_empty_output_without_budget():
    connection = ProviderConnection("c", "local", "http://127.0.0.1:1", MODEL, "openai-compatible", None, "local")
    adapter = ProviderAdapter(connection, EphemeralTestSecretStore())
    assert adapter._result_from_payload({"choices": [{"message": {"content": "FINAL"}}]}).output == "FINAL"



def test_cognitive_invoke_model_has_one_provider_call_and_separate_result(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.start()
    process = runtime.kernel.submit("contract", authority={"memory.read"})
    process = runtime.kernel.run_scheduler()[0]
    runtime.models.register(ModelRoute("contract-route", MODEL, "local", frozenset({"text"}), "local", 1.0, 0, 1, True, None))
    calls = []
    runtime.providers.register("local", lambda *_: (calls.append(1) or ProviderResponse("VESPER_READY")))
    result = runtime.cognitive.invoke_model(process.process_id, CognitiveRequest(privacy="local_only"), {"prompt": "Reply exactly: VESPER_READY"})
    assert result.success and result.output == "VESPER_READY"
    assert calls == [1]
    assert result.attempt.status == "COMPLETED"
    runtime.stop()


@pytest.mark.parametrize("credential, model, expected", [
    ("wrong-secret", MODEL, "AUTHENTICATION_FAILED"),
    (SECRET, "wrong-model", "MODEL_NOT_AVAILABLE"),
])
def test_provider_failure_is_typed_and_does_not_echo_secret(fake_provider, credential, model, expected):
    _server, base_url = fake_provider
    store = EphemeralTestSecretStore()
    ref = store.put(credential, label="local")
    route = make_route(base_url, ref)
    route = ModelRoute(**{**route.__dict__, "model_id": model})

    result = ProviderAdapters(store).invoke(route, Pack())

    assert result.output is None
    assert result.error == expected
    assert credential not in repr(result)


def test_canonical_route_reconstruction_and_runtime_restart_inference(fake_provider, tmp_path):
    _server, base_url = fake_provider
    store = EphemeralTestSecretStore()
    ref = store.put(SECRET, label="local")

    runtime_a = Runtime(tmp_path, secret_store=store)
    runtime_a.start()
    runtime_a.connections.register_provider_connection(
        connection_id="canonical-connection", display_name="Fake", base_url=base_url,
        api_style="openai-compatible", credential_ref=ref,
        endpoint_type="local", provider="local",
    )
    runtime_a.core_apps.update_settings({"model_route": {
        "status": "configured", "connection_id": "canonical-connection", "model_id": MODEL,
    }})
    process_a = runtime_a.kernel.submit("runtime-a", authority={"memory.read"})
    process_a = runtime_a.kernel.run_scheduler()[0]
    route_a = runtime_a.resolve_default_model_route()
    assert route_a.connection_id == "canonical-connection"
    assert route_a.model_id == MODEL
    assert route_a.credential_ref == ref
    assert route_a.base_url == base_url
    assert runtime_a.invoke_default_model(process_a.process_id, "Reply exactly: VESPER_READY") == "VESPER_READY"
    assert len(FakeProviderHandler.requests) == 1
    runtime_a.stop()

    runtime_b = Runtime(tmp_path, secret_store=store)
    runtime_b.start()
    assert runtime_b.secret_store is runtime_b.providers.secret_store
    route_b = runtime_b.resolve_default_model_route()
    assert route_b.connection_id == route_a.connection_id
    assert route_b.model_id == route_a.model_id
    process_b = runtime_b.kernel.submit("runtime-b", authority={"memory.read"})
    process_b = runtime_b.kernel.run_scheduler()[0]
    assert runtime_b.invoke_default_model(process_b.process_id, "Reply exactly: VESPER_READY") == "VESPER_READY"
    assert len(FakeProviderHandler.requests) == 2
    runtime_b.stop()


def test_canonical_route_missing_states_are_typed(tmp_path):
    runtime = Runtime(tmp_path, secret_store=EphemeralTestSecretStore())
    runtime.start()
    with pytest.raises(Exception) as unconfigured:
        runtime.resolve_default_model_route()
    assert getattr(unconfigured.value, "code", None) == "MODEL_NOT_CONFIGURED"
    runtime.core_apps.update_settings({"model_route": {"status": "configured", "connection_id": "missing", "model_id": MODEL}})
    with pytest.raises(Exception) as missing_connection:
        runtime.resolve_default_model_route()
    assert getattr(missing_connection.value, "code", None) == "CONNECTION_NOT_FOUND"
    runtime.connections.register_provider_connection(connection_id="no-credential", display_name="No credential", base_url="http://127.0.0.1", api_style="openai-compatible", endpoint_type="local")
    runtime.core_apps.update_settings({"model_route": {"status": "configured", "connection_id": "no-credential", "model_id": MODEL}})
    with pytest.raises(Exception) as missing_credential:
        runtime.resolve_default_model_route()
    assert getattr(missing_credential.value, "code", None) == "CREDENTIAL_NOT_CONFIGURED"
    runtime.stop()


def test_runtime_restart_missing_secret_preserves_canonical_state(fake_provider, tmp_path):
    _server, base_url = fake_provider
    store_a = EphemeralTestSecretStore()
    ref = store_a.put(SECRET, label="local")
    runtime_a = Runtime(tmp_path, secret_store=store_a)
    runtime_a.start()
    runtime_a.connections.register_provider_connection(connection_id="preserved", display_name="Fake", base_url=base_url, api_style="openai-compatible", credential_ref=ref, endpoint_type="local", provider="local")
    runtime_a.core_apps.update_settings({"model_route": {"status": "configured", "connection_id": "preserved", "model_id": MODEL}})
    route = runtime_a.resolve_default_model_route()
    runtime_a.stop()

    runtime_b = Runtime(tmp_path, secret_store=EphemeralTestSecretStore())
    runtime_b.start()
    restored = runtime_b.resolve_default_model_route()
    assert restored.connection_id == route.connection_id
    assert restored.model_id == route.model_id
    process = runtime_b.kernel.submit("missing-secret", authority={"memory.read"})
    process = runtime_b.kernel.run_scheduler()[0]
    with pytest.raises(Exception) as failure:
        runtime_b.invoke_default_model(process.process_id, "Reply exactly: VESPER_READY")
    assert getattr(failure.value, "code", None) == "CREDENTIAL_UNAVAILABLE"
    assert runtime_b.resolve_default_model_route().connection_id == "preserved"
    runtime_b.stop()
