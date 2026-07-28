from fastapi.testclient import TestClient

from vesper.api import create_app
from vesper.api import Runtime


def test_dashboard_today_exposes_daily_workflow_contract(tmp_path):
    runtime = Runtime(tmp_path / "dashboard.db")
    runtime.start()
    app = create_app(runtime)
    client = TestClient(app)
    response = client.get("/api/dashboard/today", headers={"host": "127.0.0.1"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"processes", "lanes", "approvals", "effects", "memory"}
    assert isinstance(body["processes"], list)
    assert isinstance(body["lanes"], list)
    assert isinstance(body["approvals"], list)
    assert isinstance(body["effects"], list)
    assert body["memory"]["available"] is True


def test_dashboard_contract_is_safe_when_no_external_connections_configured(tmp_path):
    runtime = Runtime(tmp_path / "dashboard.db")
    runtime.start()
    client = TestClient(create_app(runtime))
    response = client.get("/api/dashboard/today", headers={"host": "127.0.0.1"})
    assert response.status_code == 200
    body = response.json()
    assert "credentials" not in body
    assert all("secret" not in str(item).lower() for item in body["lanes"])
    assert all("token" not in str(item).lower() for item in body["lanes"])

    runtime.storage.stop()
