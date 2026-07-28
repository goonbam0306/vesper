from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.lanes import LaneDefinition


def make_lane(version: int) -> LaneDefinition:
    return LaneDefinition(
        lane_id="research", version=version, name="Research", purpose="bounded research",
        input_schema={"required": ["query"]}, output_schema={"type": "object"},
        context_policy={"max_items": 10}, tool_profile={"tools": ["search"]},
        permission_ceiling={"network": "read"}, model_policy={"capabilities": ["reasoning"]},
        evaluation_contract={"required": ["source_check"]},
    )


def test_registry_contract_and_history_are_inspectable(tmp_path):
    runtime = Runtime(tmp_path / "lane.db")
    runtime.start()
    try:
        runtime.lanes.register(make_lane(1))
        runtime.lanes.register(make_lane(2))
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        assert [x["version"] for x in client.get("/api/lanes/research/history").json()["lanes"]] == [1, 2]
        contract = client.get("/api/lanes/research/1/contract")
        assert contract.status_code == 200
        assert contract.json()["contract"]["permission_ceiling"] == {"network": "read"}
    finally:
        runtime.stop()
