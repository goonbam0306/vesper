from pathlib import Path

import pytest

from vesper.api import Runtime
from vesper.kernel import InvalidTransition, ProcessStatus


def runtime(tmp_path: Path) -> Runtime:
    return Runtime(tmp_path)


def test_aging_eventually_selects_background_despite_continuous_interactive_arrivals(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        background = rt.kernel.submit("old-background", priority="BACKGROUND")
        selected: list[str] = []
        for index in range(8):
            interactive = rt.kernel.submit(f"interactive-{index}", priority="INTERACTIVE")
            ran = rt.kernel.run_scheduler(max_slices=1)
            selected.extend(process.process_id for process in ran)
            if background.process_id in selected:
                break
            assert interactive.process_id in selected
        assert background.process_id in selected
    finally:
        rt.stop()


@pytest.mark.parametrize("upstream_status", [ProcessStatus.FAILED, ProcessStatus.CANCELLED])
def test_failed_or_cancelled_dependency_blocks_dependent_with_typed_outcome(tmp_path: Path, upstream_status: ProcessStatus):
    rt = runtime(tmp_path)
    rt.start()
    try:
        upstream = rt.kernel.submit("upstream")
        dependent = rt.kernel.submit("dependent")
        rt.kernel.add_dependency(dependent.process_id, upstream.process_id)
        rt.kernel.transition(upstream.process_id, ProcessStatus.RUNNING)
        rt.kernel.transition(upstream.process_id, upstream_status)

        with pytest.raises(InvalidTransition, match="dependency"):
            rt.kernel.transition(dependent.process_id, ProcessStatus.RUNNING)

        outcomes = rt.kernel.dependency_outcomes(dependent.process_id)
        assert outcomes == [{
            "process_id": upstream.process_id,
            "status": upstream_status,
            "outcome": "BLOCKED_BY_DEPENDENCY",
        }]
        assert rt.kernel.get(dependent.process_id).status == ProcessStatus.CREATED

        replacement = rt.kernel.submit("upstream-retry")
        assert replacement.process_id != upstream.process_id
    finally:
        rt.stop()
