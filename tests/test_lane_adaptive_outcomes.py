import json
from pathlib import Path

import pytest

from vesper.api import Runtime
from vesper.lane_invocations import LaneInvocationStatus
from vesper.lanes import LaneDefinition
from vesper.model_runtime import ModelRoute


@pytest.mark.parametrize(
    "disposition,control",
    [
        ("NEED_CONTEXT", {"reason": "missing", "requested_refs_or_kinds": ["map"]}),
        ("EXPAND", {"reason": "more", "proposed_work_units": [{"unit_id": "u1", "lane_id": "test-explore", "objective": "x"}]}),
        ("REPLAN", {"reason": "changed", "new_evidence_refs": ["a"], "invalidated_assumptions": ["b"]}),
    ],
)
def test_adaptive_outcome_parses_without_graph_or_child_mutation(tmp_path: Path, disposition: str, control: dict):
    runtime = Runtime(tmp_path)
    runtime.start()
    try:
        process = runtime.kernel.submit("lane-cognition")
        runtime.lanes.register(LaneDefinition(
            lane_id="test-explore", version=1, name="Test Explore",
            purpose="bounded evidence", input_schema={"type": "object"},
            output_schema={"type": "object"}, context_policy={},
        ))
        route = ModelRoute("fake-route", "fake-model", "fake", frozenset({"text"}), "local", 0, 0, 1000, True, None)
        runtime.providers.register("fake", lambda _r, _p: type("Response", (), {
            "output": json.dumps({"result": {"note": "bounded"}, "outcome": {"disposition": disposition, "control_request": control}}),
            "error": None, "input_tokens": 1, "output_tokens": 1, "cached_tokens": 0,
        })())
        invocation = runtime.lane_invocations.create(process.process_id, "test-explore", version=1)
        result = runtime.lane_invocations.execute(invocation.invocation_id, {"question": "x"}, route=route)
        assert result.outcome.disposition.value == disposition
        assert result.invocation.status == LaneInvocationStatus.COMPLETED
        assert len(runtime.lane_invocations.list(process.process_id)) == 1
    finally:
        runtime.stop()


def test_provider_substitution_does_not_change_pinned_lane_identity(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    try:
        process = runtime.kernel.submit("lane-cognition")
        runtime.lanes.register(LaneDefinition(
            lane_id="test-explore", version=1, name="Test Explore", purpose="bounded",
            input_schema={"type": "object"}, output_schema={"type": "object"}, context_policy={},
        ))
        route = ModelRoute("route-b", "model-b", "provider-b", frozenset({"text"}), "local", 0, 0, 1000, True, None)
        runtime.providers.register("provider-b", lambda _r, _p: type("Response", (), {
            "output": '{"result":{"ok":true},"outcome":{"disposition":"COMPLETE"}}',
            "error": None, "input_tokens": 1, "output_tokens": 1, "cached_tokens": 0,
        })())
        invocation = runtime.lane_invocations.create(process.process_id, "test-explore", version=1)
        result = runtime.lane_invocations.execute(invocation.invocation_id, {"question": "x"}, route=route)
        assert (result.invocation.lane_id, result.invocation.lane_version) == ("test-explore", 1)
    finally:
        runtime.stop()
