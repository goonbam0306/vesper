from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def test_syscall_approval_api_flow(tmp_path):
    runtime = Runtime(tmp_path)
    app = create_app(runtime)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        token = client.get("/api/bootstrap").json()["session"]
        headers = {"X-Vesper-Bootstrap": token}
        process = client.post("/api/processes", json={"origin": "director"}, headers=headers).json()["process"]
        process_id = process["process_id"]
        pending = client.post(f"/api/processes/{process_id}/syscalls", json={"operation": "test.effect", "target": "api", "args": {"value": "ok"}}, headers=headers)
        assert pending.status_code == 200
        approval_id = pending.json()["approval_id"]
        approved = client.post(f"/api/approvals/{approval_id}", json={"decision": "APPROVED"}, headers=headers)
        assert approved.status_code == 200
        committed = client.post(f"/api/processes/{process_id}/syscalls", json={"operation": "test.effect", "target": "api", "args": {"value": "ok"}, "approval_id": approval_id}, headers=headers)
        assert committed.status_code == 200
        assert committed.json()["status"] == "COMMITTED"
        assert committed.json()["effect_id"]
        assert client.get(f"/api/processes/{process_id}").json()["process"]["status"] == "WAITING"
    runtime.stop()
