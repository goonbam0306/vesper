from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def test_export_requires_absolute_destination(tmp_path):
    runtime = Runtime(tmp_path / "export.db")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"X-Vesper-Bootstrap": runtime.bootstrap_token}
        response = client.post("/api/data/export", headers=headers, json={"destination": "relative-export"})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "ABSOLUTE_DESTINATION_REQUIRED"


def test_export_returns_secret_free_manifest(tmp_path):
    runtime = Runtime(tmp_path / "export-success.db")
    destination = tmp_path / "bundle"
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"X-Vesper-Bootstrap": runtime.bootstrap_token}
        response = client.post("/api/data/export", headers=headers, json={"destination": str(destination)})
        assert response.status_code == 200
        payload = response.json()
        assert payload["format"] == "vesper-safe-export-v1"
        assert "secret" not in response.text.lower()
        assert (destination / "manifest.json").is_file()


__all__ = []

