from pathlib import Path

import pytest

from vesper.api import Runtime
from vesper.lane_invocations import (
    LaneInvocationInvalidTransitionError,
    LaneInvocationLaneDisabledError,
    LaneInvocationLaneNotFoundError,
    LaneInvocationProcessNotFoundError,
    LaneInvocationStatus,
)
from vesper.lanes import LaneDefinition


def runtime(tmp_path: Path) -> Runtime:
    instance = Runtime(tmp_path)
    instance.start()
    return instance


def lane(version: int, *, enabled: bool = True) -> LaneDefinition:
    return LaneDefinition(
        lane_id="test-explore", version=version, name="Test Explore",
        purpose="Explore a bounded question", input_schema={"type": "object"},
        output_schema={"type": "object"}, enabled=enabled,
    )


def test_exact_version_binding(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("lane-test")
        instance.lanes.register(lane(1)); instance.lanes.register(lane(2))
        invocation = instance.lane_invocations.create(process.process_id, "test-explore", version=1)
        instance.lanes.set_enabled("test-explore", 1, False)
        assert invocation.lane_version == 1
        assert instance.lane_invocations.get(invocation.invocation_id).lane_version == 1
    finally:
        instance.stop()


def test_latest_resolution_and_disabled_explicit_version(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("lane-test")
        instance.lanes.register(lane(1)); instance.lanes.register(lane(2))
        latest = instance.lane_invocations.create(process.process_id, "test-explore")
        assert latest.lane_version == 2
        instance.lanes.set_enabled("test-explore", 2, False)
        fallback = instance.lane_invocations.create(process.process_id, "test-explore")
        assert fallback.lane_version == 1
        with pytest.raises(LaneInvocationLaneDisabledError):
            instance.lane_invocations.create(process.process_id, "test-explore", version=2)
    finally:
        instance.stop()


def test_missing_process_and_lane_rejected(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        with pytest.raises(LaneInvocationProcessNotFoundError):
            instance.lane_invocations.create("missing", "test-explore")
        process = instance.kernel.submit("lane-test")
        with pytest.raises(LaneInvocationLaneNotFoundError):
            instance.lane_invocations.create(process.process_id, "missing")
    finally:
        instance.stop()


def test_lifecycle_and_invalid_transitions(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("lane-test"); instance.lanes.register(lane(1))
        invocation = instance.lane_invocations.create(process.process_id, "test-explore")
        assert invocation.status == LaneInvocationStatus.CREATED
        with pytest.raises(LaneInvocationInvalidTransitionError):
            instance.lane_invocations.complete(invocation.invocation_id)
        assert instance.lane_invocations.get(invocation.invocation_id).status == LaneInvocationStatus.CREATED
        running = instance.lane_invocations.start(invocation.invocation_id)
        completed = instance.lane_invocations.complete(running.invocation_id, "artifact:test")
        assert completed.status == LaneInvocationStatus.COMPLETED
        with pytest.raises(LaneInvocationInvalidTransitionError):
            instance.lane_invocations.cancel(completed.invocation_id)
    finally:
        instance.stop()


def test_failure_and_cancellation(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("lane-test"); instance.lanes.register(lane(1))
        first = instance.lane_invocations.create(process.process_id, "test-explore")
        failed = instance.lane_invocations.fail(instance.lane_invocations.start(first.invocation_id).invocation_id, {"class": "TIMEOUT"})
        assert failed.status == LaneInvocationStatus.FAILED
        second = instance.lane_invocations.create(process.process_id, "test-explore")
        assert instance.lane_invocations.cancel(second.invocation_id).status == LaneInvocationStatus.CANCELLED
    finally:
        instance.stop()


def test_restart_persistence(tmp_path: Path):
    first = runtime(tmp_path)
    process = first.kernel.submit("lane-test"); first.lanes.register(lane(1))
    invocation = first.lane_invocations.create(process.process_id, "test-explore")
    first.lane_invocations.start(invocation.invocation_id); first.stop()
    second = runtime(tmp_path)
    try:
        restored = second.lane_invocations.get(invocation.invocation_id)
        assert restored.status == LaneInvocationStatus.RUNNING
        assert restored.lane_version == 1
    finally:
        second.stop()
