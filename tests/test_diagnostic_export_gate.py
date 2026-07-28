from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def test_diagnostic_export_redacts_sensitive_values(tmp_path):
    instance = Runtime(tmp_path)
    with TestClient(create_app(instance)) as client:
        response = client.get("/api/diagnostics/export", headers={"host": "127.0.0.1"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"processes", "effects", "events", "lanes"}
    text = str(body).lower()
    assert "api_key" not in text
    assert "authorization" not in text
    assert "password" not in text
    instance.stop()


def test_diagnostic_export_is_structured_and_json_serializable(tmp_path):
    instance = Runtime(tmp_path)
    with TestClient(create_app(instance)) as client:
        response = client.get("/api/diagnostics/export", headers={"host": "127.0.0.1"})
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json()["events"], list)
    instance.stop()
