from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.lanes import LaneDefinition


def lane(version: int) -> LaneDefinition:
    return LaneDefinition(
        lane_id="research",
        version=version,
        name=f"Research {version}",
        purpose="bounded research",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def test_lane_lifecycle_is_director_controllable_via_api(tmp_path):
    runtime = Runtime(tmp_path / "api.db")
    runtime.start()
    try:
        runtime.lanes.register(lane(1))
        runtime.lanes.register(lane(2))
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")

        headers = {"X-Vesper-Bootstrap": runtime.bootstrap_token}
        response = client.post("/api/lanes/research/1/retire", headers=headers)
        assert response.status_code == 200
        assert response.json()["lane"]["lifecycle_state"] == "RETIRED"

        response = client.post(
            "/api/lanes/research/1/supersede",
            json={"replacement_version": 2},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()["lane"]
        assert body["lifecycle_state"] == "SUPERSEDED"
        assert body["superseded_by_version"] == 2

        latest = client.get("/api/lanes/research/latest")
        assert latest.status_code == 200
        assert latest.json()["lane"]["version"] == 2
    finally:
        runtime.stop()


def test_lane_api_rejects_missing_replacement(tmp_path):
    runtime = Runtime(tmp_path / "api.db")
    runtime.start()
    try:
        runtime.lanes.register(lane(1))
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        response = client.post(
            "/api/lanes/research/1/supersede",
            json={},
            headers={"X-Vesper-Bootstrap": runtime.bootstrap_token},
        )
        assert response.status_code == 422
    finally:
        runtime.stop()
