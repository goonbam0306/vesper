"""Deterministic Gate B scheduler pressure benchmark.

Thresholds remain tunable: this test reports metrics and only rejects semantic starvation.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vesper.api import Runtime


def run_pressure(background_count: int = 500) -> dict[str, float | int | bool]:
    with tempfile.TemporaryDirectory() as directory:
        rt = Runtime(Path(directory))
        rt.start()
        try:
            for index in range(background_count):
                rt.kernel.submit(f"benchmark-background-{index}", priority="BACKGROUND")
            interactive = rt.kernel.submit("benchmark-interactive", priority="INTERACTIVE")
            started = time.perf_counter()
            ran = rt.kernel.run_scheduler(max_slices=1)
            latency_ms = (time.perf_counter() - started) * 1000
            metrics = rt.kernel.scheduler_metrics()
            return {
                "interactive_scheduling_latency_ms": latency_ms,
                "interactive_selected": bool(ran and ran[0].process_id == interactive.process_id),
                "background_queue_depth": int(metrics["background_queue_depth"]),
                "queue_wait_ms": float(metrics["interactive_scheduling_latency_ms"]),
                "starvation": bool(metrics["interactive_starved"]),
                "runnable_processes": int(metrics["runnable_processes"]),
                "waiting_processes": int(metrics["waiting_processes"]),
            }
        finally:
            rt.stop()


def run_aging_fairness_pressure(interactive_arrivals: int = 20) -> dict[str, int | bool]:
    with tempfile.TemporaryDirectory() as directory:
        rt = Runtime(Path(directory))
        rt.start()
        try:
            background = rt.kernel.submit("benchmark-aged-background", priority="BACKGROUND")
            selected_slice = 0
            for index in range(1, interactive_arrivals + 1):
                rt.kernel.submit(f"benchmark-interactive-{index}", priority="INTERACTIVE")
                ran = rt.kernel.run_scheduler(max_slices=1)
                if ran and ran[0].process_id == background.process_id:
                    selected_slice = index
                    break
            return {
                "background_selected": selected_slice > 0,
                "background_selected_slice": selected_slice,
                "background_age_slices_tunable": rt.kernel.scheduler.background_age_slices,
            }
        finally:
            rt.stop()


def test_scheduler_pressure_no_interactive_starvation():
    result = run_pressure()
    assert result["interactive_selected"] is True
    assert result["starvation"] is False
    assert result["background_queue_depth"] > 0


def test_scheduler_aging_fairness_under_continuous_interactive_load():
    result = run_aging_fairness_pressure()
    assert result["background_selected"] is True
    assert result["background_selected_slice"] <= result["background_age_slices_tunable"] + 1


if __name__ == "__main__":
    print(json.dumps({"priority_pressure": run_pressure(), "aging_fairness": run_aging_fairness_pressure()}, sort_keys=True))
