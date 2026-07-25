from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vesper.api import create_app


def _client(tmp_path: Path) -> TestClient:
    from vesper.api import Runtime
    return TestClient(create_app(Runtime(home=tmp_path)))


HOST = {"Host": "127.0.0.1"}


def _headers(client: TestClient) -> dict[str, str]:
    return {"Host": "127.0.0.1", "X-Vesper-Bootstrap": client.get("/api/bootstrap", headers=HOST).json()["session"]}


def test_fresh_first_boot_is_canonical_and_persists_restart(tmp_path: Path):
    with _client(tmp_path) as client:
        assert client.get("/api/first-boot", headers=HOST).json()["first_boot_completed"] is False
        result = client.post("/api/first-boot/complete", headers=_headers(client), json={"director_display_name": "Director", "model_route": {"status": "unconfigured"}})
        assert result.status_code == 200
        assert client.get("/api/first-boot", headers=HOST).json()["first_boot_completed"] is True
    with _client(tmp_path) as restarted:
        state = restarted.get("/api/first-boot", headers=HOST).json()
        assert state["first_boot_completed"] is True
        assert state["director_display_name"] == "Director"


def test_connection_failure_never_persists_plaintext(tmp_path: Path):
    secret = "do-not-store-this-credential"
    with _client(tmp_path) as client:
        result = client.post("/api/first-boot/connection", headers=_headers(client), json={
            "provider": "custom", "display_name": "Test", "base_url": "http://127.0.0.1:1/v1", "api_style": "openai-compatible", "credential": secret,
        })
        assert result.status_code == 422
        assert secret not in result.text
    db = sqlite3.connect(tmp_path / "vesper.sqlite3")
    dump = "\n".join(str(row) for row in db.execute("SELECT * FROM provider_connections"))
    assert secret not in dump


def test_existing_state_is_not_reset_by_migration(tmp_path: Path):
    with _client(tmp_path) as client:
        response = client.post("/api/projects", headers=_headers(client), json={"name": "Existing project"})
        assert response.status_code == 200
        assert client.get("/api/first-boot", headers=HOST).json()["first_boot_completed"] is False
        assert client.get("/api/projects", headers=HOST).json()["projects"][0]["name"] == "Existing project"


def test_provider_connection_read_api_redacts_credential_ref(tmp_path: Path, monkeypatch):
    from vesper.secret_store import EphemeralTestSecretStore
    with _client(tmp_path) as client:
        app = client.app
        app.state.runtime.secret_store = EphemeralTestSecretStore()
        original_put = app.state.runtime.secret_store.put
        def put(value: str, *, label: str) -> str:
            assert value == "super-secret"
            return original_put(value, label=label)
        app.state.runtime.secret_store.put = put
        class FakeResponse:
            status = 200
            def read(self, _limit):
                import json
                return json.dumps({"choices": [{"message": {"content": "VESPER_MODEL_READY"}}], "usage": {}}).encode()
            def __enter__(self): return self
            def __exit__(self, *args): return False
        class FakeOpener:
            def open(self, *args, **kwargs): return FakeResponse()
        monkeypatch.setattr("vesper.api.urllib.request.build_opener", lambda *args, **kwargs: FakeOpener())
        result = client.post("/api/first-boot/connection", headers=_headers(client), json={
            "provider": "local", "display_name": "Local", "base_url": "http://127.0.0.1:8080/v1", "api_style": "openai-compatible", "credential": "super-secret", "model_id": "fixture-model",
        })
        assert result.status_code == 200
        assert "super-secret" not in result.text and "credential_ref" not in result.text
        listed = client.get("/api/connections", headers=HOST).text
        assert "super-secret" not in listed and "credential_ref" not in listed
        db = sqlite3.connect(tmp_path / "vesper.sqlite3")
        ref = db.execute("SELECT credential_ref FROM provider_connections").fetchone()[0]
        assert ref.startswith("secret://test/") and "super-secret" not in ref


def test_frontend_does_not_persist_credential():
    source = (ROOT / "frontend/src/main.tsx").read_text()
    assert "localStorage" not in source
    assert "setSetupCredential('')" in source
    assert "Welcome to Vesper" in source
