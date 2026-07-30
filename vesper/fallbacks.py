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
    success_count: int = 0
    failure_count: int = 0
    recurrence_count: int = 0
    context_admission: tuple[str, ...] = ()
    stop_semantics: tuple[str, ...] = ()
    existing_lane_id: str | None = None

    @property
    def semantic_tokens(self) -> frozenset[str]:
        words = set(self.inferred_function_label.lower().replace("-", " ").split())
        for value in self.cognitive_operations + self.input_types + self.output_shape:
            words.update(value.lower().replace("-", " ").split())
        aliases = {"investigate": "research", "investigation": "research", "summarize": "report", "summarization": "report"}
        return frozenset(aliases.get(word, word) for word in words)

    @property
    def operational_features(self) -> frozenset[str]:
        return frozenset(self.tool_profile + self.permission_shape + self.evaluation_dimensions + self.context_admission + self.stop_semantics)

    @property
    def reliability(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total else 0.0

    @property
    def boundary_features(self) -> frozenset[str]:
        return frozenset(self.tool_profile + self.output_shape + self.evaluation_dimensions + self.permission_shape + self.context_admission + self.stop_semantics)


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
    evidence: tuple[tuple[str, float], ...] = ()


class CandidateBuilder:
    def build(self, records: Iterable[FallbackRecord], *, threshold: float = 0.65) -> AbstractionCandidate:
        values = tuple(records)
        if len(values) < 2:
            raise ValueError("at least two fallback records are required")
        anchor = values[0]
        fingerprints = [FallbackFingerprint.from_record(value) for value in values]
        structural = sum(anchor_fp.similarity(fp) for anchor_fp, fp in zip([fingerprints[0]] * len(fingerprints[1:]), fingerprints[1:])) / max(1, len(values) - 1)
        semantic = sum(self._jaccard(anchor.semantic_tokens, value.semantic_tokens) for value in values[1:]) / max(1, len(values) - 1)
        operational = sum(self._jaccard(anchor.operational_features, value.operational_features) for value in values[1:]) / max(1, len(values) - 1)
        boundary = sum(self._jaccard(anchor.boundary_features, value.boundary_features) for value in values[1:]) / max(1, len(values) - 1)
        reliability = sum(value.reliability for value in values) / len(values)
        frequency = min(1.0, sum(value.recurrence_count for value in values) / max(1, len(values) * 3))
        if structural < threshold and semantic < 0.35:
            raise ValueError("fallback cluster is neither structurally nor semantically stable")
        if operational < 0.2:
            raise ValueError("fallback cluster has insufficient shared operational evidence")
        contract_mismatch = any(value.evaluation_dimensions != anchor.evaluation_dimensions and value.tool_profile == anchor.tool_profile for value in values[1:])
        if contract_mismatch and len(values) == 2:
            raise ValueError("fallback cluster has a materially distinct evaluation contract")
        score = 0.25 * structural + 0.15 * semantic + 0.25 * operational + 0.2 * boundary + 0.1 * reliability + 0.05 * frequency
        differing_boundary = len(set(value.boundary_features for value in values)) > 1
        boundary_groups = {value.boundary_features for value in values}
        if differing_boundary and len(values) >= 3 and frequency >= 0.5 and reliability >= 0.5 and semantic >= 0.5:
            recommendation, reason = "NEW_LANE", "repeated execution has a materially distinct operational boundary"
        elif len(values) < 3 or score < 0.62:
            recommendation, reason = "INSUFFICIENT_EVIDENCE", "insufficient repeated and reliable evidence"
        elif anchor.existing_lane_id and all(value.existing_lane_id == anchor.existing_lane_id for value in values) and semantic >= 0.35:
            recommendation, reason = "EXISTING_LANE_WITH_SKILL", "existing Lane boundary matches and only context/Skill varies"
        else:
            recommendation, reason = "SKILL", "reusable cognitive pattern within the same execution boundary"
        canonical = anchor.cognitive_operations[0] if anchor.cognitive_operations else "fallback-cognition"
        evidence = (("structural", structural), ("semantic", semantic), ("operational", operational), ("boundary", boundary), ("reliability", reliability), ("frequency", frequency), ("combined", score))
        return AbstractionCandidate(tuple(value.fallback_id for value in values), canonical, recommendation, recommendation_reason=reason, evidence=evidence)

    @staticmethod
    def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
        union = left | right
        return len(left & right) / len(union) if union else 1.0


__all__ = ["AbstractionCandidate", "CandidateBuilder", "FallbackFingerprint", "FallbackRecord"]
