from pathlib import Path

from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def test_health_is_available_only_on_loopback(tmp_path: Path):
    runtime = Runtime(tmp_path)
    with TestClient(create_app(runtime)) as client:
        assert client.get("/health", headers={"host": "127.0.0.1"}).status_code == 200
        assert client.get("/health", headers={"host": "10.0.0.8"}).status_code == 400


def test_mutation_requires_bootstrap_session(tmp_path: Path):
    runtime = Runtime(tmp_path)
    with TestClient(create_app(runtime)) as client:
        assert client.post("/api/director", json={"preferred_name": "Director"}, headers={"host": "127.0.0.1"}).status_code == 401
        token = client.get("/api/bootstrap", headers={"host": "127.0.0.1"}).json()["session"]
        response = client.post(
            "/api/director",
            json={"preferred_name": "Director"},
            headers={"host": "127.0.0.1", "x-vesper-bootstrap": token},
        )
        assert response.status_code == 200
