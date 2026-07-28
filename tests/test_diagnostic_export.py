from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def test_diagnostic_export_excludes_secrets_and_hidden_reasoning(tmp_path):
    runtime = Runtime(tmp_path)
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        response = client.get("/api/diagnostics/export", headers={"X-Vesper-Bootstrap": runtime.bootstrap_token})
    assert response.status_code == 200
    body = response.json()
    assert "processes" in body and "events" in body
    assert "api_key" not in str(body).lower()
    assert "chain_of_thought" not in str(body).lower()