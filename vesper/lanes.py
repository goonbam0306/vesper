"""Kernel-owned durable LaneDefinition metadata."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .adaptive_execution import LaneOutcomeDisposition
from .storage import Storage


class LaneError(RuntimeError):
    code = "LANE_ERROR"


class LaneInvalidError(LaneError):
    code = "LANE_INVALID"


class LaneDuplicateError(LaneError):
    code = "LANE_VERSION_EXISTS"


class LaneNotFoundError(LaneError):
    code = "LANE_NOT_FOUND"


class LaneVersionNotFoundError(LaneError):
    code = "LANE_VERSION_NOT_FOUND"


class LaneLifecycleError(LaneError):
    code = "LANE_LIFECYCLE_INVALID"


@dataclass(frozen=True)
class LaneDefinition:
    lane_id: str
    version: int
    name: str
    purpose: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    context_policy: dict[str, Any] = field(default_factory=dict)
    tool_profile: dict[str, Any] = field(default_factory=dict)
    permission_ceiling: dict[str, Any] = field(default_factory=dict)
    capability_requirements: dict[str, Any] = field(default_factory=dict)
    model_policy: dict[str, Any] = field(default_factory=dict)
    escalation_policy: dict[str, Any] = field(default_factory=dict)
    stop_conditions: dict[str, Any] = field(default_factory=dict)
    evaluation_contract: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    lifecycle_state: str = "ACTIVE"
    superseded_by_version: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class CoreLaneContract:
    definition: LaneDefinition
    allowed_outcomes: frozenset[LaneOutcomeDisposition]


_JSON_FIELDS = (
    "input_schema", "output_schema", "context_policy", "tool_profile",
    "permission_ceiling", "capability_requirements", "model_policy",
    "escalation_policy", "stop_conditions", "evaluation_contract",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate(definition: LaneDefinition) -> None:
    if not isinstance(definition.lane_id, str) or not definition.lane_id.strip():
        raise LaneInvalidError("lane_id must be non-empty")
    if not isinstance(definition.version, int) or isinstance(definition.version, bool) or definition.version <= 0:
        raise LaneInvalidError("version must be a positive integer")
    if not isinstance(definition.purpose, str) or not definition.purpose.strip():
        raise LaneInvalidError("purpose must be non-empty")
    for name in ("input_schema", "output_schema"):
        value = getattr(definition, name)
        if not isinstance(value, dict):
            raise LaneInvalidError(f"{name} must be structured")


def _from_row(row: sqlite3.Row) -> LaneDefinition:
    values: dict[str, Any] = {
        key: row[key]
        for key in row.keys()
        if not key.endswith("_json")
    }
    for name in _JSON_FIELDS:
        values[name] = json.loads(row[f"{name}_json"])
    values["enabled"] = bool(values["enabled"])
    values.setdefault("lifecycle_state", "ACTIVE" if values["enabled"] else "RETIRED")
    values.setdefault("superseded_by_version", None)
    return LaneDefinition(**values)


class LaneRegistry:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def register(self, definition: LaneDefinition) -> LaneDefinition:
        _validate(definition)
        now = _now()
        value = asdict(definition)
        value["created_at"] = definition.created_at or now
        value["updated_at"] = definition.updated_at or now

        def operation(conn: sqlite3.Connection) -> LaneDefinition:
            try:
                conn.execute(
                    "INSERT INTO lane_definitions "
                    "(lane_id,version,name,purpose,input_schema_json,output_schema_json,context_policy_json,"
                    "tool_profile_json,permission_ceiling_json,capability_requirements_json,model_policy_json,"
                    "escalation_policy_json,stop_conditions_json,evaluation_contract_json,enabled,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (value["lane_id"], value["version"], value["name"], value["purpose"],
                     *[json.dumps(value[name], sort_keys=True) for name in _JSON_FIELDS],
                     int(value["enabled"]), value["created_at"], value["updated_at"]),
                )
            except sqlite3.IntegrityError as exc:
                if "lane_definitions.lane_id" in str(exc):
                    raise LaneDuplicateError("lane version already exists") from exc
                raise
            return value_definition(value)
        return self.storage.write(operation)

    def latest(self, lane_id: str, *, enabled_only: bool = True) -> LaneDefinition:
        def operation(conn: sqlite3.Connection):
            query = "SELECT * FROM lane_definitions WHERE lane_id=?"
            params: list[Any] = [lane_id]
            if enabled_only:
                query += " AND enabled=1"
            query += " ORDER BY version DESC LIMIT 1"
            return conn.execute(query, params).fetchone()
        row = self.storage.write(operation)
        if row is None:
            raise LaneNotFoundError("lane not found")
        return _from_row(row)

    def list(self, lane_id: str | None = None) -> list[LaneDefinition]:
        def operation(conn: sqlite3.Connection):
            if lane_id is None:
                return conn.execute("SELECT * FROM lane_definitions ORDER BY lane_id, version").fetchall()
            return conn.execute("SELECT * FROM lane_definitions WHERE lane_id=? ORDER BY version", (lane_id,)).fetchall()
        return [_from_row(row) for row in self.storage.write(operation)]

    def set_enabled(self, lane_id: str, version: int, enabled: bool) -> LaneDefinition:
        current = self.get(lane_id, version)
        if current.lifecycle_state in {"RETIRED", "SUPERSEDED"} and enabled:
            raise LaneLifecycleError("retired or superseded Lane cannot be silently reactivated")
        def operation(conn: sqlite3.Connection):
            cursor = conn.execute(
                "UPDATE lane_definitions SET enabled=?, updated_at=? WHERE lane_id=? AND version=?",
                (int(enabled), _now(), lane_id, version),
            )
            if cursor.rowcount == 0:
                raise LaneVersionNotFoundError("lane version not found")
            return conn.execute("SELECT * FROM lane_definitions WHERE lane_id=? AND version=?", (lane_id, version)).fetchone()
        return _from_row(self.storage.write(operation))

    def retire(self, lane_id: str, version: int) -> LaneDefinition:
        return self._set_lifecycle(lane_id, version, "RETIRED", None)

    def supersede(self, lane_id: str, version: int, replacement_version: int) -> LaneDefinition:
        if version == replacement_version:
            raise LaneLifecycleError("a Lane version cannot supersede itself")
        replacement = self.get(lane_id, replacement_version)
        if replacement.lifecycle_state != "ACTIVE" or not replacement.enabled:
            raise LaneLifecycleError("replacement Lane must be active")
        return self._set_lifecycle(lane_id, version, "SUPERSEDED", replacement_version)

    def _set_lifecycle(self, lane_id: str, version: int, state: str, replacement: int | None) -> LaneDefinition:
        def operation(conn: sqlite3.Connection):
            cursor = conn.execute(
                "UPDATE lane_definitions SET enabled=?, lifecycle_state=?, superseded_by_version=?, updated_at=? WHERE lane_id=? AND version=?",
                (int(state == "ACTIVE"), state, replacement, _now(), lane_id, version),
            )
            if cursor.rowcount == 0:
                raise LaneVersionNotFoundError("lane version not found")
            return conn.execute("SELECT * FROM lane_definitions WHERE lane_id=? AND version=?", (lane_id, version)).fetchone()
        return _from_row(self.storage.write(operation))

    def get(self, lane_id: str, version: int) -> LaneDefinition:
        def operation(conn: sqlite3.Connection):
            return conn.execute("SELECT * FROM lane_definitions WHERE lane_id=? AND version=?", (lane_id, version)).fetchone()
        row = self.storage.write(operation)
        if row is None:
            raise LaneVersionNotFoundError("lane version not found")
        return _from_row(row)


def value_definition(value: dict[str, Any]) -> LaneDefinition:
    return LaneDefinition(**value)


def _core_definition(
    lane_id: str,
    name: str,
    purpose: str,
    output_artifact: str,
    *,
    inputs: tuple[str, ...],
    context: dict[str, Any],
    tools: dict[str, Any],
    permissions: dict[str, Any],
    capabilities: tuple[str, ...],
    evaluation: tuple[str, ...],
    allowed: frozenset[LaneOutcomeDisposition],
) -> CoreLaneContract:
    definition = LaneDefinition(
        lane_id=lane_id,
        version=1,
        name=name,
        purpose=purpose,
        input_schema={"type": "object", "required": list(inputs)},
        output_schema={"type": "object", "artifact": output_artifact},
        context_policy=context,
        tool_profile=tools,
        permission_ceiling=permissions,
        capability_requirements={"capabilities": list(capabilities)},
        model_policy={"selection": "weakest_sufficient", "provider_independent": True},
        escalation_policy={"director_approval_required": True, "mode": "bounded"},
        stop_conditions={
            "complete": "objective_satisfied_and_required_artifact_produced",
            "need_context": "insufficient_information",
            "expand": "additional_bounded_work_required",
            "replan": "broader_execution_assumption_invalid",
            "blocked": "external_dependency",
            "fail": "bounded_execution_failure",
        },
        evaluation_contract={"dimensions": list(evaluation)},
    )
    return CoreLaneContract(definition, allowed)


_CORE_ALLOWED = frozenset(LaneOutcomeDisposition)


def core_lane_catalog() -> tuple[CoreLaneContract, ...]:
    """Return the immutable, provider-independent version-1 core catalog.

    Reading the catalog has no persistence or runtime mutation side effects.
    """
    return (
        _core_definition("explore", "Explore", "Acquire relevant evidence.", "EvidencePack", inputs=("search_scope",), context={"focus": ("search_scope", "known_references", "source_constraints")}, tools={"operations": ("read", "search", "retrieve")}, permissions={"effects": "none"}, capabilities=("evidence_synthesis", "tool_reasoning"), evaluation=("relevance", "provenance", "coverage"), allowed=_CORE_ALLOWED),
        _core_definition("analyze", "Analyze", "Interpret evidence and derive structured findings.", "AnalysisRecord", inputs=("evidence",), context={"focus": ("evidence", "constraints", "known_references")}, tools={"operations": ("read", "search", "retrieve"), "mutation": False}, permissions={"effects": "none"}, capabilities=("evidence_synthesis", "structured_output"), evaluation=("evidence_grounding", "consistency"), allowed=_CORE_ALLOWED),
        _core_definition("plan", "Plan", "Convert goals, evidence, constraints, and state into a structured execution proposal.", "ExecutionGraphProposal", inputs=("goal", "evidence", "constraints", "state"), context={"focus": ("goal", "evidence", "constraints", "state")}, tools={"operations": ("read", "search", "retrieve"), "scheduling": False}, permissions={"effects": "none", "graph_mutation": False}, capabilities=("planning", "structured_output"), evaluation=("dependency_validity", "constraint_coverage"), allowed=_CORE_ALLOWED),
        _core_definition("code", "Code", "Perform bounded implementation cognition and propose software changes.", "PatchSet", inputs=("requirements", "repository_context"), context={"focus": ("requirements", "repository_context", "constraints")}, tools={"operations": ("read", "search", "retrieve"), "propose_patch": True}, permissions={"effects": "none", "file_writes": False, "shell": False, "deployment": False}, capabilities=("code_reasoning", "tool_reasoning"), evaluation=("behavior", "compatibility", "patch_coherence"), allowed=_CORE_ALLOWED),
        _core_definition("diagnose", "Diagnose", "Determine causes or causal structure of an observed problem.", "Diagnosis", inputs=("observed_problem", "evidence"), context={"focus": ("observed_problem", "evidence", "affected_components", "uncertainty")}, tools={"operations": ("read", "search", "retrieve"), "causal_investigation": True}, permissions={"effects": "none"}, capabilities=("causal_reasoning", "evidence_synthesis"), evaluation=("causal_evidence", "competing_hypotheses", "uncertainty"), allowed=frozenset({LaneOutcomeDisposition.COMPLETE, LaneOutcomeDisposition.NEED_CONTEXT, LaneOutcomeDisposition.EXPAND, LaneOutcomeDisposition.REPLAN, LaneOutcomeDisposition.BLOCKED, LaneOutcomeDisposition.FAIL})),
        _core_definition("verify", "Verify", "Evaluate produced work against explicit requirements and evidence.", "VerificationReport", inputs=("produced_work", "acceptance_criteria", "execution_results"), context={"focus": ("acceptance_criteria", "execution_results", "evidence")}, tools={"operations": ("read", "search", "retrieve"), "execution": "kernel_results_only"}, permissions={"effects": "none", "test_execution": False}, capabilities=("evidence_synthesis", "structured_output"), evaluation=("explicit_acceptance_criteria", "evidence_support"), allowed=frozenset({LaneOutcomeDisposition.COMPLETE, LaneOutcomeDisposition.NEED_CONTEXT, LaneOutcomeDisposition.BLOCKED, LaneOutcomeDisposition.FAIL})),
        _core_definition("compose", "Compose", "Convert validated artifacts and conclusions into a communication artifact.", "DocumentArtifact", inputs=("validated_artifacts", "conclusions"), context={"focus": ("validated_artifacts", "conclusions", "audience", "format")}, tools={"operations": ("read",), "source_fidelity_required": True}, permissions={"effects": "none"}, capabilities=("structured_output",), evaluation=("fidelity_to_validated_source_artifacts",), allowed=frozenset({LaneOutcomeDisposition.COMPLETE, LaneOutcomeDisposition.NEED_CONTEXT, LaneOutcomeDisposition.BLOCKED, LaneOutcomeDisposition.FAIL})),
    )


def install_core_lanes(registry: LaneRegistry) -> tuple[LaneDefinition, ...]:
    """Explicitly and idempotently install missing core versions without enabling existing rows."""
    installed: list[LaneDefinition] = []
    for contract in core_lane_catalog():
        try:
            existing = registry.get(contract.definition.lane_id, contract.definition.version)
        except LaneVersionNotFoundError:
            installed.append(registry.register(contract.definition))
        else:
            installed.append(existing)
    return tuple(installed)


__all__ = [
    "CoreLaneContract", "LaneDefinition", "LaneDuplicateError", "LaneError",
    "LaneInvalidError", "LaneNotFoundError", "LaneRegistry", "LaneVersionNotFoundError",
    "core_lane_catalog", "install_core_lanes",
]
