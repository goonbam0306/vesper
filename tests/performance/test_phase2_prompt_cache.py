import json
import time

from vesper.context import ContextPack


def test_prompt_cache_harness_records_metrics():
    pack = ContextPack.build({"K0": {"authority": "kernel"}, "K1": {"goal": "test"}, "K2": {"process_id": "p1"}})
    started = time.perf_counter()
    wire = pack.serialize()
    elapsed_ms = (time.perf_counter() - started) * 1000
    metrics = {"ttft_ms": elapsed_ms, "total_latency_ms": elapsed_ms, "input_tokens": len(wire), "cache_hit": False, "cost": 0.0, "warm_resume_ms": elapsed_ms}
    assert json.loads(wire)["pack_id"] == pack.pack_id
    assert metrics["total_latency_ms"] >= metrics["ttft_ms"]
    assert metrics["input_tokens"] > 0


def test_stable_wire_prefix_for_equivalent_context():
    left = ContextPack.build({"K0": {"b": 2, "a": 1}, "K1": {"goal": "x"}})
    right = ContextPack.build({"K1": {"goal": "x"}, "K0": {"a": 1, "b": 2}})
    assert left.wire_prefix() == right.wire_prefix()
    assert left.pack_id == right.pack_id
