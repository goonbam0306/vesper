import pytest

from vesper.api import Runtime
from vesper.lanes import LaneLifecycleError
from tests.test_phase11_lane_lifecycle_gate import definition


def test_disabled_lane_stays_disabled_until_explicit_enable(tmp_path):
    runtime = Runtime(tmp_path / "lanes.db")
    runtime.start()
    try:
        runtime.lanes.register(definition(1))
        disabled = runtime.lanes.set_enabled("research", 1, False)
        assert disabled.enabled is False
        assert runtime.lanes.latest("research", enabled_only=False).enabled is False
        enabled = runtime.lanes.set_enabled("research", 1, True)
        assert enabled.enabled is True
    finally:
        runtime.stop()


def test_retired_lane_cannot_be_silently_reactivated(tmp_path):
    runtime = Runtime(tmp_path / "lanes.db")
    runtime.start()
    try:
        runtime.lanes.register(definition(1))
        runtime.lanes.retire("research", 1)
        with pytest.raises(LaneLifecycleError):
            runtime.lanes.set_enabled("research", 1, True)
    finally:
        runtime.stop()

