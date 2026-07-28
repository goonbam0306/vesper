from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.lanes import LaneDefinition


def _lane(version: int) -> LaneDefinition:
    return LaneDefinition(
        lane_id="research",
        version=version,
        name=f"Research {version}",
        purpose="bounded research",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def test_authenticated_lane_lifecycle_api_flow_and_ui_mapping(tmp_path):
    runtime = Runtime(tmp_path / "lane-ui.db")
    runtime.start()
    try:
        runtime.lanes.register(_lane(1))
        runtime.lanes.register(_lane(2))
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        headers = {"X-Vesper-Bootstrap": runtime.bootstrap_token}

        shell = client.get("/dashboard/lanes")
        assert shell.status_code == 200
        for marker in ("enable-lane", "disable-lane", "retire-lane", "supersede-lane", "laneAction"):
            assert marker in shell.text

        assert client.post("/api/lanes/research/1/enabled", headers=headers, json={"enabled": False}).json()["lane"]["enabled"] is False
        retired = client.post("/api/lanes/research/1/retire", headers=headers)
        assert retired.json()["lane"]["lifecycle_state"] == "RETIRED"
        superseded = client.post("/api/lanes/research/1/supersede", headers=headers, json={"replacement_version": 2})
        assert superseded.json()["lane"]["lifecycle_state"] == "SUPERSEDED"
        assert client.get("/api/lanes/research/latest").json()["lane"]["version"] == 2
    finally:
        runtime.stop()


__all__ = []

