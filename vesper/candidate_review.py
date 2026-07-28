"""Review and approval boundary for fallback-derived abstraction candidates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from .fallbacks import AbstractionCandidate


class CandidateReviewError(ValueError):
    """Raised when a candidate review transition is invalid."""


@dataclass(frozen=True)
class CandidateReview:
    candidate: AbstractionCandidate
    reviewer: str
    evidence: tuple[str, ...]
    decision: str = "PENDING"
    note: str = ""
    approval_id: str | None = None
    decided_at: str | None = None
    activated: bool = False


class CandidateReviewStore:
    def __init__(self) -> None:
        self._reviews: dict[tuple[str, ...], CandidateReview] = {}

    def submit(self, candidate: AbstractionCandidate, *, reviewer: str, evidence: tuple[str, ...]) -> CandidateReview:
        if not reviewer.strip():
            raise CandidateReviewError("reviewer is required")
        if not evidence:
            raise CandidateReviewError("review evidence is required")
        review = CandidateReview(candidate, reviewer, tuple(evidence))
        self._reviews[candidate.supporting_fallback_ids] = review
        return review

    def get(self, candidate: AbstractionCandidate) -> CandidateReview:
        try:
            return self._reviews[candidate.supporting_fallback_ids]
        except KeyError as exc:
            raise CandidateReviewError("candidate has not been submitted for review") from exc

    def activate(self, candidate: AbstractionCandidate, *, approval_id: str) -> CandidateReview:
        current = self.get(candidate)
        if current.decision != "APPROVED" or current.approval_id != approval_id:
            raise CandidateReviewError("candidate requires a matching approval")
        if current.activated:
            return current
        updated = CandidateReview(current.candidate, current.reviewer, current.evidence, current.decision, current.note, current.approval_id, current.decided_at, True)
        self._reviews[candidate.supporting_fallback_ids] = updated
        return updated

    def decide(self, candidate: AbstractionCandidate, *, reviewer: str, approved: bool, note: str = "") -> CandidateReview:
        current = self.get(candidate)
        if current.reviewer != reviewer:
            raise CandidateReviewError("only the submitting reviewer may decide")
        if current.decision != "PENDING":
            return current
        decision = "APPROVED" if approved else "REJECTED"
        decided_at = datetime.now(timezone.utc).isoformat()
        approval_id = sha256("|".join((*candidate.supporting_fallback_ids, reviewer, decision, decided_at)).encode()).hexdigest()[:24]
        updated = CandidateReview(current.candidate, current.reviewer, current.evidence, decision, note, approval_id, decided_at, False)
        self._reviews[candidate.supporting_fallback_ids] = updated
        return updated


__all__ = ["CandidateReview", "CandidateReviewError", "CandidateReviewStore"]


def review_payload(review: CandidateReview) -> dict[str, Any]:
    return {
        "supporting_fallback_ids": list(review.candidate.supporting_fallback_ids),
        "canonical_function": review.candidate.canonical_function,
        "recommended_abstraction": review.candidate.recommended_abstraction,
        "activation_status": review.candidate.activation_status,
        "reviewer": review.reviewer,
        "evidence": list(review.evidence),
        "decision": review.decision,
        "note": review.note,
        "approval_id": review.approval_id,
        "decided_at": review.decided_at,
        "activated": review.activated,
    }


__all__ += ["review_payload"]
