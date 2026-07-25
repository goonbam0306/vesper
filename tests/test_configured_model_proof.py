from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from tests.e2e_secret_store import FileBackedTestSecretStore


class FakeProvider(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def do_POST(self):
        size = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(size))
        self.__class__.calls.append({"path": self.path, "authorization": self.headers.get("authorization"), "body": body})
        payload = {"choices": [{"message": {"content": "VESPER_READY"}}]}
        encoded = json.dumps(payload).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


def test_configured_model_proof_and_restart(tmp_path: Path):
    FakeProvider.calls = []
    server = HTTPServer(("127.0.0.1", 0), FakeProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    secret_root = tmp_path / "secret-store"
    marker = "VESPER_E2E_SECRET_test-only"
    home = tmp_path / "home"
    try:
        store = FileBackedTestSecretStore(secret_root)
        runtime = Runtime(home, secret_store=store); runtime.start()
        with TestClient(create_app(runtime)) as client:
            endpoint = f"http://127.0.0.1:{server.server_port}/v1"
            response = client.post("/api/first-boot/connection", headers={"host": "127.0.0.1", "x-vesper-bootstrap": runtime.bootstrap_token}, json={"provider": "local", "display_name": "Test Provider", "base_url": endpoint, "api_style": "openai-compatible", "credential": marker, "model_id": "vesper-test-model"})
            assert response.status_code == 200, response.text
            connection_id = response.json()["connection"]["connection_id"]
            assert FakeProvider.calls[-1]["authorization"] == f"Bearer {marker}"
            response = client.post("/api/first-boot/complete", headers={"host": "127.0.0.1", "x-vesper-bootstrap": runtime.bootstrap_token}, json={"director_display_name": "Director", "model_route": {"status": "configured", "connection_id": connection_id, "model_id": "vesper-test-model", "provider": "local", "endpoint_type": "local", "api_style": "openai-compatible"}})
            assert response.status_code == 200, response.text
            response = client.post("/api/model/invoke", headers={"host": "127.0.0.1", "x-vesper-bootstrap": runtime.bootstrap_token}, json={"prompt": "normal runtime"})
            assert response.status_code == 200 and response.json()["output"] == "VESPER_READY"
        runtime.stop()
        restarted = Runtime(home, secret_store=FileBackedTestSecretStore(secret_root)); restarted.start()
        with TestClient(create_app(restarted)) as client:
            assert client.get("/api/first-boot", headers={"host": "127.0.0.1", "x-vesper-bootstrap": restarted.bootstrap_token}).json()["first_boot_completed"] is True
            response = client.post("/api/model/invoke", headers={"host": "127.0.0.1", "x-vesper-bootstrap": restarted.bootstrap_token}, json={"prompt": "after restart"})
            assert response.status_code == 200 and response.json()["output"] == "VESPER_READY"
        restarted.stop()
        assert len(FakeProvider.calls) == 3
    finally:
        server.shutdown(); server.server_close()
