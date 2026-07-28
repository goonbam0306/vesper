from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.kernel import ProcessStatus


def test_audit_export_contains_recovery_cursor_and_durable_events(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.start()
    process = runtime.kernel.submit("director", client_request_id="audit-gate")
    runtime.kernel.transition(process.process_id, ProcessStatus.RUNNING)
    recovered = runtime.kernel.recover_running_processes()
    assert recovered == (process.process_id,)
    with TestClient(create_app(runtime)) as client:
        response = client.get("/api/diagnostics/export", headers={"host": "127.0.0.1"})
    assert response.status_code == 200
    body = response.json()
    assert body["recovery"]["cursor"] >= 1
    assert body["recovery"]["event_count"] == len(body["events"])
    assert any(event["process_id"] == process.process_id for event in body["events"])
    runtime.stop()


def test_audit_export_has_effect_history_collection(tmp_path):
    runtime = Runtime(tmp_path)
    with TestClient(create_app(runtime)) as client:
        body = client.get("/api/diagnostics/export", headers={"host": "127.0.0.1"}).json()
    assert isinstance(body["effects"], list)
    assert "recovery" in body
    runtime.stop()
