from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.kernel import InvalidTransition, IdempotencyConflict, Kernel, ProcessStatus


def runtime(tmp_path: Path) -> Runtime:
    return Runtime(tmp_path)


def test_lifecycle_terminal_is_irreversible(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        p = rt.kernel.submit("director")
        p = rt.kernel.transition(p.process_id, ProcessStatus.RUNNING)
        p = rt.kernel.transition(p.process_id, ProcessStatus.COMPLETED)
        assert p.status == ProcessStatus.COMPLETED
        with pytest.raises(InvalidTransition):
            rt.kernel.transition(p.process_id, ProcessStatus.RUNNING)
    finally:
        rt.stop()


def test_volatile_promotes_same_process_id(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        p = rt.kernel.submit("query", volatile=True)
        promoted = rt.kernel.promote(p.process_id)
        assert promoted.process_id == p.process_id
        assert promoted.volatile is False
    finally:
        rt.stop()


def test_idempotency_and_conflict(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        first = rt.kernel.submit("director", client_request_id="req-1")
        again = rt.kernel.submit("director", client_request_id="req-1")
        assert first.process_id == again.process_id
        with pytest.raises(IdempotencyConflict):
            rt.kernel.submit("other", client_request_id="req-1")
    finally:
        rt.stop()


def test_query_snapshot_does_not_create_process(tmp_path: Path):
    rt = runtime(tmp_path)
    with TestClient(create_app(rt)) as client:
        headers = {"host": "127.0.0.1"}
        before = client.get("/api/snapshot", headers=headers).json()
        after = client.get("/api/snapshot", headers=headers).json()
        assert before["processes"] == after["processes"] == []


def test_system_api_command_and_watch(tmp_path: Path):
    rt = runtime(tmp_path)
    with TestClient(create_app(rt)) as client:
        headers = {"host": "127.0.0.1", "x-vesper-bootstrap": rt.bootstrap_token}
        response = client.post("/api/processes", headers={**headers, "x-client-request-id": "api-1"}, json={"origin": "director"})
        assert response.status_code == 200
        process = response.json()["process"]
        events = client.get("/api/watch?cursor=0", headers={"host": "127.0.0.1"}).json()["events"]
        assert any(event["process_id"] == process["process_id"] for event in events)
