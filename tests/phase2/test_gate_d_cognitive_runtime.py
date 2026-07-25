from pathlib import Path
import json

import pytest

from vesper.api import Runtime
from vesper.context import ContextPack
from vesper.memory import RetrievalStatus
from vesper.model_runtime import (
    CognitiveRequest,
    FailureClassification,
    ModelRoute,
    ProviderResponse,
)


def running_process(runtime: Runtime):
    process = runtime.kernel.submit("gate-d", authority={"memory.read"})
    return runtime.kernel.run_scheduler()[0]


def test_l2_working_memory_is_process_scoped_and_context_packs_are_fresh(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    first = running_process(runtime)
    second = running_process(runtime)
    memory = runtime.memory.put(kind="note", payload={"text": "only first"}, scope_refs=("team",))
    runtime.memory.page_in(first.process_id, memory)

    assert [item.memory_id for item in runtime.memory.l2(first.process_id)] == [memory.memory_id]
    assert runtime.memory.l2(second.process_id) == ()

    pack_one = runtime.cognitive.build_context(first.process_id, {"goal": "one"})
    pack_two = runtime.cognitive.build_context(first.process_id, {"goal": "two"})
    assert pack_one.pack_id != pack_two.pack_id
    assert "goal" not in pack_two.frames.get("K5", {})
    runtime.stop()


def test_retrieval_preserves_conflict_staleness_and_distinguishes_empty_states(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    runtime.memory.put(kind="fact", payload={"key": "weather", "value": "sun"}, scope_refs=("a",), provenance={"source": "one"})
    runtime.memory.put(kind="fact", payload={"key": "weather", "value": "rain"}, scope_refs=("a",), provenance={"source": "two"})
    runtime.memory.put(kind="fact", payload={"text": "old only"}, scope_refs=("a",), validity="STALE")

    assert runtime.memory.retrieve("weather", scope_refs=("a",)).status == RetrievalStatus.CONFLICT
    assert runtime.memory.retrieve("old", scope_refs=("a",)).status == RetrievalStatus.STALE_ONLY
    assert runtime.memory.retrieve("missing", scope_refs=("a",)).status == RetrievalStatus.NOT_FOUND
    assert runtime.memory.retrieve("", scope_refs=("a",)).status == RetrievalStatus.INSUFFICIENT
    runtime.stop()


def test_hybrid_fusion_relations_and_cycles_are_deterministic_and_bounded(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    left = runtime.memory.put(kind="note", payload={"text": "alpha"}, scope_refs=("a",))
    right = runtime.memory.put(kind="note", payload={"text": "alpha beta"}, scope_refs=("a",))
    runtime.memory.relate(left.memory_id, right.memory_id, "supports")
    runtime.memory.relate(right.memory_id, left.memory_id, "supports")

    one = runtime.memory.retrieve("alpha", scope_refs=("a",), relation_depth=1, relation_limit=2)
    two = runtime.memory.retrieve("alpha", scope_refs=("a",), relation_depth=1, relation_limit=2)
    assert one.status == two.status
    assert [item.memory_id for item in one.items] == [item.memory_id for item in two.items]
    assert len(one.items) <= 2
    assert all(item.provenance.get("retrieval") for item in one.items)
    runtime.stop()


def test_context_admission_redacts_secrets_and_rejects_unauthorized_evidence(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    process = running_process(runtime)
    safe = runtime.memory.put(kind="note", payload={"text": "safe", "secret": "raw-secret"}, scope_refs=("a",))
    forbidden = runtime.memory.put(kind="note", payload={"text": "forbidden"}, scope_refs=("b",))
    runtime.memory.page_in(process.process_id, safe)
    runtime.memory.page_in(process.process_id, forbidden)

    pack = runtime.cognitive.build_context(process.process_id, {"goal": "use safe"}, allowed_scopes=("a",))
    encoded = pack.serialize()
    assert "raw-secret" not in encoded
    assert "forbidden" not in encoded
    assert pack.frames["K3"]["evidence"][0]["memory_id"] == safe.memory_id
    runtime.stop()


def test_page_fault_retrieves_pages_in_builds_new_pack_and_resumes_without_escalation(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    process = running_process(runtime)
    runtime.memory.put(kind="note", payload={"text": "needed evidence"}, scope_refs=("a",))
    request = CognitiveRequest(capabilities=frozenset({"text"}), privacy="local_only")

    first = runtime.cognitive.invoke(process.process_id, request, {"goal": "answer"}, information_need="needed evidence", allowed_scopes=("a",))
    assert first.status == "PAGE_FAULT"
    old_pack = runtime.cognitive.context_manifest(first.context_pack_id)
    assert runtime.kernel.get(process.process_id).status == "WAITING"

    resumed = runtime.cognitive.resolve_page_fault(first.attempt_id)
    assert resumed.status == "COMPLETED"
    assert resumed.context_pack_id != first.context_pack_id
    assert runtime.cognitive.context_manifest(first.context_pack_id) == old_pack
    assert runtime.kernel.get(process.process_id).status == "RUNNING"
    assert resumed.route_id == first.route_id
    assert resumed.failure_classification != FailureClassification.ESCALATION
    runtime.stop()


def test_provider_fallback_preserves_privacy_and_telemetry_distinguishes_actions(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    runtime.models.register(ModelRoute("local-fail", "small", "local", frozenset({"text"}), "local", .91, 0, 10, True, None))
    runtime.models.register(ModelRoute("remote", "large", "openai_compatible", frozenset({"text"}), "remote", .99, 1, 20, True, "secret://remote"))
    process = running_process(runtime)
    request = CognitiveRequest(capabilities=frozenset({"text"}), privacy="local_only")
    runtime.providers.register("local", lambda *_: ProviderResponse.failure("transient"))

    result = runtime.cognitive.invoke(process.process_id, request, {"goal": "answer"})
    assert result.status == "FAILED"
    telemetry = runtime.cognitive.telemetry(result.attempt_id)
    assert telemetry["failure_classification"] == FailureClassification.RETRY
    assert telemetry["fallback_reason"] is None
    assert "secret://remote" not in str(telemetry)
    runtime.stop()


def test_page_fault_resume_invokes_same_route_and_records_provider_cache_metrics(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    runtime.models.register(ModelRoute("local-cache", "small", "local", frozenset({"text"}), "local", .91, 0, 10, True, None))
    runtime.models.register(ModelRoute("local-default", "default", "local", frozenset({"text"}), "local", .90, 0, 10, False, None))
    runtime.providers.register("local", lambda *_: ProviderResponse("resumed", input_tokens=11, output_tokens=3, cached_tokens=7))
    process = running_process(runtime)
    runtime.memory.put(kind="note", payload={"text": "needed evidence"}, scope_refs=("a",))

    fault = runtime.cognitive.invoke(process.process_id, CognitiveRequest(privacy="local_only"), {"goal": "answer"}, information_need="needed evidence", allowed_scopes=("a",))
    resumed = runtime.cognitive.resolve_page_fault(fault.attempt_id)

    assert resumed.status == "COMPLETED"
    assert resumed.route_id == fault.route_id == "local-cache"
    telemetry = runtime.cognitive.telemetry(resumed.attempt_id)
    assert telemetry["input_tokens"] == 11
    assert telemetry["output_tokens"] == 3
    assert telemetry["cached_tokens"] == 7
    assert telemetry["cache_hit"] is True
    assert json.loads(telemetry["stable_prefix_id"])["K0"]["identity"].startswith("You are Vesper")
    runtime.stop()


def test_provider_adapter_categories_are_explicit_and_never_emit_credential_reference(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    process = running_process(runtime)
    for provider in ("official", "openai_compatible", "local"):
        runtime.models.register(ModelRoute(f"{provider}-route", provider, provider, frozenset({"text"}), "local", .90, 0, 10, True, "secret://opaque"))
        runtime.providers.register(provider, lambda *_: ProviderResponse("ok"))
    request = CognitiveRequest(privacy="local_only")
    attempt = runtime.cognitive.invoke(process.process_id, request, {"goal": "safe"})
    assert attempt.status == "COMPLETED"
    assert "secret://opaque" not in str(runtime.cognitive.telemetry(attempt.attempt_id))
    assert "secret://opaque" not in (runtime.cognitive.context_manifest(attempt.context_pack_id) or "")
    runtime.stop()


def test_wire_prefix_is_k0_only_and_dynamic_call_contract_does_not_change_it():
    first = ContextPack.build({"K0": {"kernel": "stable"}, "K1": {"goal": "a"}})
    second = ContextPack.build({"K0": {"kernel": "stable"}, "K1": {"goal": "b"}})
    assert first.wire_prefix() == second.wire_prefix()
    assert first.dynamic_suffix() != second.dynamic_suffix()
    assert "goal" not in first.wire_prefix()


@pytest.mark.parametrize("status", [RetrievalStatus.AMBIGUOUS, RetrievalStatus.INSUFFICIENT, RetrievalStatus.NOT_FOUND, RetrievalStatus.STALE_ONLY])
def test_unresolved_retrieval_statuses_are_never_coerced_to_resolved(tmp_path: Path, status):
    runtime = Runtime(tmp_path)
    runtime.start()
    result = runtime.cognitive.retrieval_outcome(status)
    assert result.status == status
    assert result.status != RetrievalStatus.RESOLVED
    runtime.stop()
