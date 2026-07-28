from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.lanes import install_core_lanes


def test_lane_enable_disable_api_preserves_explicit_state(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.start()
    install_core_lanes(runtime.lanes)
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"X-Vesper-Bootstrap": runtime.bootstrap_token}
        lane = client.get("/api/lanes", headers=headers).json()["lanes"][0]
        response = client.post(f"/api/lanes/{lane['lane_id']}/{lane['version']}/enabled", headers=headers, json={"enabled": False})
        assert response.status_code == 200
        assert response.json()["lane"]["enabled"] is False