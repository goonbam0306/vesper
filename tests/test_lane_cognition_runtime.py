import json
from pathlib import Path

import pytest

from vesper.api import Runtime
from vesper.adaptive_execution import LaneOutcomeDisposition
from vesper.lane_invocations import LaneInvocationStatus
from vesper.lanes import LaneDefinition
from vesper.model_runtime import ModelRoute


class FakeProvider:
    def __init__(self, output: str):
        self.output = output

    def invoke(self, prompt, *, max_output_tokens):
        return type("Response", (), {
            "output": self.output, "error": None, "input_tokens": 1,
            "output_tokens": 1, "cached_tokens": 0,
        })()


def make_runtime(tmp_path: Path) -> Runtime:
    runtime = Runtime(tmp_path)
    runtime.start()
    return runtime


def install_lane(runtime: Runtime) -> str:
    process = runtime.kernel.submit("lane-cognition")
    runtime.lanes.register(LaneDefinition(
        lane_id="test-explore", version=1, name="Test Explore",
        purpose="bounded evidence acquisition", input_schema={"type": "object"},
        output_schema={"type": "object", "artifact": "EvidencePack"},
        context_policy={"focus": ("question",)},
    ))
    return process.process_id


def test_lane_runtime_executes_structured_complete_with_exact_contract(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    try:
        process_id = install_lane(runtime)
        route = ModelRoute("fake-route", "fake-model", "fake", frozenset({"text"}), "local", 0, 0, 1000, True, None)
        runtime.providers.register("fake", lambda _route, _pack: type("Response", (), {
            "output": '{"result":{"evidence":["a"]},"outcome":{"disposition":"COMPLETE"}}',
            "error": None, "input_tokens": 1, "output_tokens": 1, "cached_tokens": 0,
        })())
        invocation = runtime.lane_invocations.create(process_id, "test-explore", version=1)
        result = runtime.lane_invocations.execute(
            invocation.invocation_id, {"question": "What exists?"}, route=route
        )
        assert result.invocation.lane_version == 1
        assert result.invocation.status == LaneInvocationStatus.COMPLETED
        assert result.outcome.disposition is LaneOutcomeDisposition.COMPLETE
        assert result.primary_result == {"evidence": ["a"]}
    finally:
        runtime.stop()


def test_lane_runtime_rejects_malformed_provider_output(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    try:
        process_id = install_lane(runtime)
        route = ModelRoute("fake-route", "fake-model", "fake", frozenset({"text"}), "local", 0, 0, 1000, True, None)
        runtime.providers.register("fake", lambda _route, _pack: type("Response", (), {
            "output": "not-json", "error": None, "input_tokens": 1,
            "output_tokens": 1, "cached_tokens": 0,
        })())
        invocation = runtime.lane_invocations.create(process_id, "test-explore", version=1)
        with pytest.raises(ValueError):
            runtime.lane_invocations.execute(invocation.invocation_id, {"question": "x"}, route=route)
        assert runtime.lane_invocations.get(invocation.invocation_id).status == LaneInvocationStatus.FAILED
    finally:
        runtime.stop()