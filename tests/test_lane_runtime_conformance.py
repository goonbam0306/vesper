from pathlib import Path

from vesper.api import Runtime
from vesper.lane_invocations import LaneInvocationStatus
from vesper.lanes import LaneDefinition


def test_invocation_state_survives_runtime_restart(tmp_path: Path):
    first = Runtime(tmp_path)
    first.start()
    process = first.kernel.submit("restart-check")
    first.lanes.register(LaneDefinition(
        lane_id="restart-lane", version=1, name="Restart", purpose="bounded",
        input_schema={"type": "object"}, output_schema={"type": "object"}, context_policy={},
    ))
    invocation = first.lane_invocations.create(process.process_id, "restart-lane", version=1, tool_grants=("none",))
    first.lane_invocations.start(invocation.invocation_id)
    first.lane_invocations.fail(invocation.invocation_id, {"classification": "TEST"})
    first.stop()

    second = Runtime(tmp_path)
    second.start()
    try:
        restored = second.lane_invocations.get(invocation.invocation_id)
        assert restored.status == LaneInvocationStatus.FAILED
        assert restored.lane_id == "restart-lane"
        assert restored.lane_version == 1
        assert restored.tool_grants == ("none",)
    finally:
        second.stop()


def test_lane_execution_does_not_expand_tool_grants(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    try:
        process = runtime.kernel.submit("authority-check")
        runtime.lanes.register(LaneDefinition(
            lane_id="authority-lane", version=1, name="Authority", purpose="bounded",
            input_schema={"type": "object"}, output_schema={"type": "object"}, context_policy={},
        ))
        invocation = runtime.lane_invocations.create(process.process_id, "authority-lane", version=1, tool_grants=())
        assert invocation.tool_grants == ()
        assert not hasattr(runtime.lane_invocations, "grant_tool")
    finally:
        runtime.stop()
