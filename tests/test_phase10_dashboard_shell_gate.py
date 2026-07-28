from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def test_dashboard_shell_is_browser_renderable(tmp_path):
    runtime = Runtime(tmp_path / "dashboard.db")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Vesper" in response.text
        assert 'aria-label="Today"' in response.text
        assert "/api/dashboard/today" in response.text


def test_dashboard_today_api_remains_available(tmp_path):
    runtime = Runtime(tmp_path / "dashboard-api.db")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        response = client.get("/api/dashboard/today")
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


__all__ = []

