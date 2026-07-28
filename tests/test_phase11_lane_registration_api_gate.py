from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def _payload(lane_id="browser-lane"):
    return {
        "lane_id": lane_id,
        "version": 1,
        "name": "Browser Lane",
        "purpose": "isolated browser fixture",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "context_policy": {"scope": "local"},
        "permission_ceiling": {"effects": "none"},
    }


def test_authenticated_lane_registration_is_reviewable_and_disabled(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.start()
    try:
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        assert client.post("/api/lanes", json=_payload()).status_code == 401
        headers = {"X-Vesper-Bootstrap": runtime.bootstrap_token}
        response = client.post("/api/lanes", json=_payload(), headers=headers)
        assert response.status_code == 200
        lane = response.json()["lane"]
        assert lane["lane_id"] == "browser-lane"
        assert lane["enabled"] is False
        assert lane["lifecycle_state"] == "ACTIVE"
        enabled = client.post("/api/lanes/browser-lane/1/enabled", json={"enabled": True}, headers=headers)
        assert enabled.status_code == 200
        assert enabled.json()["lane"]["enabled"] is True
    finally:
        runtime.stop()


def test_lane_registration_rejects_unknown_fields(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.start()
    try:
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        headers = {"X-Vesper-Bootstrap": runtime.bootstrap_token}
        response = client.post("/api/lanes", json={**_payload(), "enabled": True}, headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "LANE_INVALID"
    finally:
        runtime.stop()
