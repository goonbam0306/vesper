from pathlib import Path

import pytest

from vesper.api import Runtime
from vesper.adaptive_execution import LaneOutcomeDisposition
from vesper.lanes import (
    LaneDefinition,
    LaneDuplicateError,
    LaneInvalidError,
    LaneNotFoundError,
    core_lane_catalog,
    install_core_lanes,
)


def make_runtime(tmp_path: Path) -> Runtime:
    runtime = Runtime(tmp_path)
    runtime.start()
    return runtime


def definition(version: int) -> LaneDefinition:
    return LaneDefinition(
        lane_id="test-explore",
        version=version,
        name="Test Explore",
        purpose="Explore a bounded question",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def test_valid_lane_registers_and_duplicate_is_rejected(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    try:
        registered = runtime.lanes.register(definition(1))
        assert registered.lane_id == "test-explore"
        assert runtime.lanes.get("test-explore", 1) == registered
        with pytest.raises(LaneDuplicateError):
            runtime.lanes.register(definition(1))
    finally:
        runtime.stop()


def test_lane_versions_remain_retrievable(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    try:
        runtime.lanes.register(definition(1))
        runtime.lanes.register(definition(2))
        assert runtime.lanes.get("test-explore", 1).version == 1
        assert runtime.lanes.get("test-explore", 2).version == 2
    finally:
        runtime.stop()


def test_latest_uses_highest_enabled_version_and_disabled_versions_remain(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    try:
        runtime.lanes.register(definition(1))
        runtime.lanes.register(definition(2))
        assert runtime.lanes.latest("test-explore").version == 2
        runtime.lanes.set_enabled("test-explore", 2, False)
        assert runtime.lanes.latest("test-explore").version == 1
        assert runtime.lanes.get("test-explore", 2).enabled is False
        assert [item.version for item in runtime.lanes.list("test-explore")] == [1, 2]
    finally:
        runtime.stop()


def test_invalid_lane_is_rejected_without_persistence(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    try:
        invalid = LaneDefinition(
            lane_id="", version=1, name="Invalid", purpose="x",
            input_schema={"type": "object"}, output_schema={"type": "object"},
        )
        with pytest.raises(LaneInvalidError):
            runtime.lanes.register(invalid)
        assert runtime.lanes.list() == []
    finally:
        runtime.stop()


def test_lane_survives_runtime_restart(tmp_path: Path):
    first = make_runtime(tmp_path)
    first.lanes.register(definition(1))
    first.stop()

    second = make_runtime(tmp_path)
    try:
        assert second.lanes.get("test-explore", 1).purpose == "Explore a bounded question"
    finally:
        second.stop()


def test_core_catalog_has_exactly_seven_provider_independent_contracts():
    catalog = core_lane_catalog()
    assert [item.definition.lane_id for item in catalog] == [
        "explore", "analyze", "plan", "code", "diagnose", "verify", "compose"
    ]
    assert all(item.definition.version == 1 for item in catalog)
    assert len({item.definition.lane_id for item in catalog}) == 7
    for item in catalog:
        assert "provider" not in item.definition.model_policy
        assert "model_id" not in item.definition.model_policy
        assert LaneOutcomeDisposition.COMPLETE in item.allowed_outcomes


def test_core_catalog_definitions_pass_existing_validation_and_boundaries_are_distinct():
    catalog = core_lane_catalog()
    by_id = {item.definition.lane_id: item.definition for item in catalog}
    assert by_id["explore"].output_schema["artifact"] == "EvidencePack"
    assert by_id["analyze"].output_schema["artifact"] == "AnalysisRecord"
    assert by_id["diagnose"].output_schema["artifact"] == "Diagnosis"
    assert by_id["code"].output_schema["artifact"] == "PatchSet"
    assert by_id["verify"].output_schema["artifact"] == "VerificationReport"
    assert by_id["compose"].output_schema["artifact"] == "DocumentArtifact"
    assert by_id["explore"].tool_profile != by_id["analyze"].tool_profile
    assert by_id["analyze"].evaluation_contract != by_id["diagnose"].evaluation_contract
    assert by_id["code"].permission_ceiling["effects"] == "none"
    assert by_id["verify"].tool_profile["execution"] == "kernel_results_only"


def test_explicit_core_install_is_idempotent_and_preserves_disabled_state(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    try:
        install_core_lanes(runtime.lanes)
        runtime.lanes.set_enabled("diagnose", 1, False)
        install_core_lanes(runtime.lanes)
        assert runtime.lanes.get("diagnose", 1).enabled is False
        with pytest.raises(LaneNotFoundError):
            runtime.lanes.latest("diagnose")
    finally:
        runtime.stop()


def test_core_install_duplicate_registration_rejects(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    try:
        install_core_lanes(runtime.lanes)
        with pytest.raises(LaneDuplicateError):
            runtime.lanes.register(core_lane_catalog()[0].definition)
    finally:
        runtime.stop()
