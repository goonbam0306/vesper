"""Immutable, kernel-facing control contracts returned by Lane execution.

These objects describe what should happen next; they do not materialize or mutate
Processes, LaneInvocations, or ExecutionGraphs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LaneOutcomeDisposition(StrEnum):
    COMPLETE = "COMPLETE"
    NEED_CONTEXT = "NEED_CONTEXT"
    EXPAND = "EXPAND"
    REPLAN = "REPLAN"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


class LaneOutcomeValidationError(ValueError):
    """Raised when an adaptive execution contract is malformed."""


@dataclass(frozen=True)
class ContextNeed:
    reason: str
    requested_refs_or_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProposedWorkUnit:
    local_id: str
    function_or_lane: str
    objective: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkExpansionProposal:
    reason: str
    proposed_work_units: tuple[ProposedWorkUnit, ...]
    parent_node_id: str | None = None
    dependency_proposal: tuple[tuple[str, str], ...] = ()
    required_capabilities: tuple[str, ...] = ()
    estimated_scope: str | None = None


@dataclass(frozen=True)
class GraphRevisionRequest:
    reason: str
    new_evidence_refs: tuple[str, ...] = ()
    invalidated_assumptions: tuple[str, ...] = ()
    source_node_id: str | None = None


@dataclass(frozen=True)
class LaneOutcome:
    disposition: LaneOutcomeDisposition
    primary_artifact_ref: str | None = None
    control_request: Any | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            normalized = LaneOutcomeDisposition(self.disposition)
        except (TypeError, ValueError) as exc:
            raise LaneOutcomeValidationError("unknown LaneOutcome disposition") from exc
        object.__setattr__(self, "disposition", normalized)


class LaneOutcomeValidator:
    """Pure deterministic validator; validation has no runtime side effects."""

    @classmethod
    def validate(cls, outcome: LaneOutcome) -> LaneOutcome:
        if not isinstance(outcome, LaneOutcome):
            raise LaneOutcomeValidationError("outcome must be a LaneOutcome")
        try:
            disposition = LaneOutcomeDisposition(outcome.disposition)
        except (TypeError, ValueError) as exc:
            raise LaneOutcomeValidationError("unknown LaneOutcome disposition") from exc

        if disposition == LaneOutcomeDisposition.COMPLETE:
            cls._forbid_control(outcome, "COMPLETE cannot carry a control request")
        elif disposition == LaneOutcomeDisposition.NEED_CONTEXT:
            cls._require_type(outcome.control_request, ContextNeed, "NEED_CONTEXT requires ContextNeed")
            cls._require_text(outcome.control_request.reason, "ContextNeed.reason")
            cls._require_nonempty(outcome.control_request.requested_refs_or_kinds, "ContextNeed.requested_refs_or_kinds")
        elif disposition == LaneOutcomeDisposition.EXPAND:
            cls._require_type(outcome.control_request, WorkExpansionProposal, "EXPAND requires WorkExpansionProposal")
            cls._validate_expansion(outcome.control_request)
        elif disposition == LaneOutcomeDisposition.REPLAN:
            cls._require_type(outcome.control_request, GraphRevisionRequest, "REPLAN requires GraphRevisionRequest")
            cls._validate_replan(outcome.control_request)
        elif disposition == LaneOutcomeDisposition.BLOCKED:
            cls._validate_mapping(outcome.control_request, ("reason", "category"), "BLOCKED")
        elif disposition == LaneOutcomeDisposition.FAIL:
            cls._validate_mapping(outcome.control_request, ("reason", "classification"), "FAIL")
        return outcome

    @staticmethod
    def _forbid_control(outcome: LaneOutcome, message: str) -> None:
        if outcome.control_request is not None:
            raise LaneOutcomeValidationError(message)

    @staticmethod
    def _require_type(value: Any, expected: type, message: str) -> None:
        if not isinstance(value, expected):
            raise LaneOutcomeValidationError(message)

    @staticmethod
    def _require_text(value: Any, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise LaneOutcomeValidationError(f"{field_name} must be non-empty")

    @staticmethod
    def _require_nonempty(value: Any, field_name: str) -> None:
        if not isinstance(value, (tuple, list)) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise LaneOutcomeValidationError(f"{field_name} must contain non-empty strings")

    @classmethod
    def _validate_expansion(cls, proposal: WorkExpansionProposal) -> None:
        cls._require_text(proposal.reason, "WorkExpansionProposal.reason")
        if not proposal.proposed_work_units:
            raise LaneOutcomeValidationError("EXPAND requires proposed work units")
        ids: set[str] = set()
        for unit in proposal.proposed_work_units:
            if not isinstance(unit, ProposedWorkUnit):
                raise LaneOutcomeValidationError("proposed work units must be ProposedWorkUnit values")
            cls._require_text(unit.local_id, "ProposedWorkUnit.local_id")
            cls._require_text(unit.function_or_lane, "ProposedWorkUnit.function_or_lane")
            cls._require_text(unit.objective, "ProposedWorkUnit.objective")
            if unit.local_id in ids or unit.local_id in unit.depends_on:
                raise LaneOutcomeValidationError("work unit IDs must be unique and cannot self-depend")
            ids.add(unit.local_id)
        for unit in proposal.proposed_work_units:
            if any(dep not in ids for dep in unit.depends_on):
                raise LaneOutcomeValidationError("work unit dependency must reference a proposed local_id")

    @classmethod
    def _validate_replan(cls, request: GraphRevisionRequest) -> None:
        cls._require_text(request.reason, "GraphRevisionRequest.reason")
        cls._require_nonempty(request.new_evidence_refs, "GraphRevisionRequest.new_evidence_refs")
        cls._require_nonempty(request.invalidated_assumptions, "GraphRevisionRequest.invalidated_assumptions")

    @classmethod
    def _validate_mapping(cls, value: Any, fields: tuple[str, ...], disposition: str) -> None:
        if not isinstance(value, dict):
            raise LaneOutcomeValidationError(f"{disposition} requires structured metadata")
        for field_name in fields:
            cls._require_text(value.get(field_name), f"{disposition}.{field_name}")


validate_lane_outcome = LaneOutcomeValidator.validate

__all__ = [
    "ContextNeed", "GraphRevisionRequest", "LaneOutcome", "LaneOutcomeDisposition",
    "LaneOutcomeValidationError", "LaneOutcomeValidator", "ProposedWorkUnit",
    "WorkExpansionProposal", "validate_lane_outcome",
]