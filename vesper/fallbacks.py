"""Operational fallback records, structural fingerprints, and approval-gated candidates."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable


@dataclass(frozen=True)
class FallbackRecord:
    fallback_id: str
    inferred_function_label: str
    cognitive_operations: tuple[str, ...]
    input_types: tuple[str, ...]
    output_shape: tuple[str, ...]
    tool_profile: tuple[str, ...]
    evaluation_dimensions: tuple[str, ...]
    permission_shape: tuple[str, ...]


@dataclass(frozen=True)
class FallbackFingerprint:
    features: frozenset[str]

    @classmethod
    def from_record(cls, record: FallbackRecord) -> "FallbackFingerprint":
        fields = (
            ("op", record.cognitive_operations),
            ("in", record.input_types),
            ("out", record.output_shape),
            ("tool", record.tool_profile),
            ("eval", record.evaluation_dimensions),
            ("perm", record.permission_shape),
        )
        return cls(frozenset(f"{prefix}:{value}" for prefix, values in fields for value in values))

    def similarity(self, other: "FallbackFingerprint") -> float:
        union = self.features | other.features
        return len(self.features & other.features) / len(union) if union else 1.0

    @property
    def stable_id(self) -> str:
        return sha256("|".join(sorted(self.features)).encode()).hexdigest()


@dataclass(frozen=True)
class AbstractionCandidate:
    supporting_fallback_ids: tuple[str, ...]
    canonical_function: str
    recommended_abstraction: str
    activation_status: str = "PENDING_DIRECTOR_APPROVAL"
    recommendation_reason: str = ""


class CandidateBuilder:
    def build(self, records: Iterable[FallbackRecord], *, threshold: float = 0.8) -> AbstractionCandidate:
        values = tuple(records)
        if len(values) < 2:
            raise ValueError("at least two fallback records are required")
        fingerprints = [FallbackFingerprint.from_record(value) for value in values]
        if any(fingerprints[0].similarity(item) < threshold for item in fingerprints[1:]):
            raise ValueError("fallback cluster is not structurally stable")
        canonical = values[0].cognitive_operations[0] if values[0].cognitive_operations else "fallback-cognition"
        # A stable cluster alone is not enough to recommend a Lane. Lane
        # promotion requires a separately identified operational contract;
        # absent that explicit signal, preserve the safer SKILL recommendation.
        recommendation = "SKILL"
        reason = "repeated stable operational contract" if recommendation == "LANE" else "reusable cognitive pattern"
        return AbstractionCandidate(tuple(value.fallback_id for value in values), canonical, recommendation, recommendation_reason=reason)


__all__ = ["AbstractionCandidate", "CandidateBuilder", "FallbackFingerprint", "FallbackRecord"]
