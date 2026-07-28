from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def test_today_exposes_fel_observability_projection(tmp_path):
    runtime = Runtime(tmp_path / "fel.db")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        response = client.get("/api/dashboard/today")
        assert response.status_code == 200
        payload = response.json()
        obs = payload["observability"]
        assert obs["process_count"] == len(payload["processes"])
        assert obs["effect_count"] == len(payload["effects"])
        assert obs["approval_count"] == len(payload["approvals"])
        assert obs["verification"] == {"source": "kernel_snapshot", "status": "available"}


def test_today_does_not_expose_credentials(tmp_path):
    runtime = Runtime(tmp_path / "fel-secrets.db")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        text = client.get("/api/dashboard/today").text.lower()
        assert "credential" not in text
        assert "secret" not in text
        assert "token" not in text


__all__ = []

