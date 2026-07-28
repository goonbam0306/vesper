import pytest

from vesper.api import Runtime
from vesper.lanes import LaneDefinition, LaneLifecycleError


def definition(version: int) -> LaneDefinition:
    return LaneDefinition(
        lane_id="research",
        version=version,
        name=f"Research {version}",
        purpose="bounded research",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def test_lane_retirement_and_supersession_are_durable(tmp_path):
    runtime = Runtime(tmp_path / "lanes.db")
    runtime.start()
    try:
        runtime.lanes.register(definition(1))
        runtime.lanes.register(definition(2))
        retired = runtime.lanes.retire("research", 1)
        assert retired.lifecycle_state == "RETIRED"
        assert retired.enabled is False
        superseded = runtime.lanes.supersede("research", 1, 2)
        assert superseded.lifecycle_state == "SUPERSEDED"
        assert superseded.superseded_by_version == 2
        assert runtime.lanes.latest("research").version == 2
    finally:
        runtime.stop()


def test_lane_cannot_supersede_with_inactive_replacement(tmp_path):
    runtime = Runtime(tmp_path / "lanes.db")
    runtime.start()
    try:
        runtime.lanes.register(definition(1))
        runtime.lanes.register(definition(2))
        runtime.lanes.retire("research", 2)
        with pytest.raises(LaneLifecycleError):
            runtime.lanes.supersede("research", 1, 2)
    finally:
        runtime.stop()
