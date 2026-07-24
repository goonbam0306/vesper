from pathlib import Path

from vesper.api import Runtime, create_app
from vesper.context import ContextPack, admit
from vesper.model_runtime import CognitiveRequest, ModelRoute
from fastapi.testclient import TestClient


def test_memory_revision_preserves_identity_and_history(tmp_path: Path):
    rt = Runtime(tmp_path)
    rt.start()
    first = rt.memory.put(kind="idea", payload={"text": "alpha"}, memory_id="m1")
    second = rt.memory.put(kind="idea", payload={"text": "beta"}, memory_id="m1")
    assert first.memory_id == second.memory_id == "m1"
    assert [item.revision for item in rt.memory.history("m1")] == [1, 2]
    rt.stop()


def test_retrieval_scope_and_ambiguity_are_explicit(tmp_path: Path):
    rt = Runtime(tmp_path)
    rt.start()
    rt.memory.put(kind="note", payload={"text": "same target"}, scope_refs=("a",))
    rt.memory.put(kind="note", payload={"text": "same target"}, scope_refs=("a",))
    result = rt.memory.retrieve("target", scope_refs=("a",))
    assert result.status == "AMBIGUOUS"
    assert rt.memory.retrieve("target", scope_refs=("b",)).status == "NOT_FOUND"
    rt.stop()


def test_context_pack_is_deterministic_and_fault_is_new_pack():
    frames = {"K0": {"authority": "kernel"}, "K3": {"evidence": ["x"]}}
    first = ContextPack.build(frames)
    second = ContextPack.build({"K3": frames["K3"], "K0": frames["K0"]})
    assert first.pack_id == second.pack_id
    faulted = first.page_fault("missing evidence")
    assert faulted.pack_id == first.pack_id
    assert faulted.fault == "missing evidence"
    assert admit(authorized=True, relevant=True, current=True, needed=True, worth_cost=True)
    assert not admit(authorized=False, relevant=True, current=True, needed=True, worth_cost=True)


def test_model_route_weakest_sufficient_and_local_preference(tmp_path: Path):
    rt = Runtime(tmp_path)
    rt.start()
    rt.models.register(ModelRoute("remote", "large", "remote", frozenset({"text", "vision"}), "remote", .99, 1, 1000, True, "ref"))
    route = rt.models.route(CognitiveRequest(capabilities=frozenset({"text"}), reliability_floor=.8))
    assert route.route_id == "local-default"
    rt.stop()


def test_http_memory_context_and_route(tmp_path: Path):
    rt = Runtime(tmp_path)
    with TestClient(create_app(rt)) as client:
        headers = {"host": "127.0.0.1", "x-vesper-bootstrap": rt.bootstrap_token}
        created = client.post("/api/memories", headers=headers, json={"kind": "note", "payload": {"text": "hello"}})
        assert created.status_code == 200
        assert client.get("/api/memory/search?q=hello", headers={"host": "127.0.0.1"}).json()["status"] == "RESOLVED"
        pack = client.post("/api/context-pack", headers=headers, json={"frames": {"K0": {"authority": "kernel"}}}).json()
        assert pack["pack_id"].startswith("ctx_")
        assert client.post("/api/model/route", headers=headers, json={"capabilities": ["text"]}).json()["route_id"] == "local-default"
        assert client.get("/api/memories/missing", headers={"host": "127.0.0.1"}).status_code == 404
