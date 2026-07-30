"""Review and approval boundary for fallback-derived abstraction candidates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import uuid
from typing import Any

from .fallbacks import AbstractionCandidate
from .storage import Storage


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
    def __init__(self, storage: Storage | None = None) -> None:
        self.storage = storage
        self._reviews: dict[tuple[str, ...], CandidateReview] = {}

    @staticmethod
    def _key(candidate: AbstractionCandidate) -> str:
        return sha256("|".join(candidate.supporting_fallback_ids).encode()).hexdigest()

    def _persist(self, review: CandidateReview) -> None:
        if self.storage is None:
            self._reviews[review.candidate.supporting_fallback_ids] = review
            return
        candidate = review.candidate
        payload = {
            "candidate_key": self._key(candidate),
            "supporting_fallback_ids_json": json.dumps(candidate.supporting_fallback_ids),
            "canonical_function": candidate.canonical_function,
            "recommended_abstraction": candidate.recommended_abstraction,
            "recommendation_reason": candidate.recommendation_reason,
            "activation_status": candidate.activation_status,
            "reviewer": review.reviewer,
            "evidence_json": json.dumps(review.evidence),
            "decision": review.decision,
            "note": review.note,
            "approval_id": review.approval_id,
            "decided_at": review.decided_at,
            "activated": int(review.activated),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        self.storage.write(lambda conn: conn.execute(
            """INSERT OR REPLACE INTO candidate_reviews
            (candidate_key, supporting_fallback_ids_json, canonical_function,
             recommended_abstraction, recommendation_reason, activation_status, reviewer, evidence_json,
             decision, note, approval_id, decided_at, activated, submitted_at)
            VALUES (:candidate_key, :supporting_fallback_ids_json, :canonical_function,
             :recommended_abstraction, :recommendation_reason, :activation_status, :reviewer, :evidence_json,
             :decision, :note, :approval_id, :decided_at, :activated, :submitted_at)""",
            payload,
        ))

    def _load(self, candidate: AbstractionCandidate) -> CandidateReview:
        if self.storage is None:
            return self._reviews[candidate.supporting_fallback_ids]
        row = self.storage.connect().execute(
            "SELECT * FROM candidate_reviews WHERE candidate_key = ?", (self._key(candidate),)
        ).fetchone()
        if row is None:
            raise KeyError(candidate.supporting_fallback_ids)
        return CandidateReview(
            candidate=candidate,
            reviewer=row["reviewer"],
            evidence=tuple(json.loads(row["evidence_json"])),
            decision=row["decision"],
            note=row["note"],
            approval_id=row["approval_id"],
            decided_at=row["decided_at"],
            activated=bool(row["activated"]),
        )

    def list(self) -> tuple[CandidateReview, ...]:
        if self.storage is None:
            return tuple(self._reviews.values())
        rows = self.storage.connect().execute(
            "SELECT * FROM candidate_reviews ORDER BY submitted_at, candidate_key"
        ).fetchall()
        return tuple(
            self._load(AbstractionCandidate(
                tuple(json.loads(row["supporting_fallback_ids_json"])),
                row["canonical_function"],
                row["recommended_abstraction"],
                row["activation_status"],
                row["recommendation_reason"],
            )) for row in rows
        )

    def submit(self, candidate: AbstractionCandidate, *, reviewer: str, evidence: tuple[str, ...]) -> CandidateReview:
        if not reviewer.strip():
            raise CandidateReviewError("reviewer is required")
        if not evidence:
            raise CandidateReviewError("review evidence is required")
        review = CandidateReview(candidate, reviewer, tuple(evidence))
        self._persist(review)
        return review

    def get(self, candidate: AbstractionCandidate) -> CandidateReview:
        try:
            return self._load(candidate)
        except KeyError as exc:
            raise CandidateReviewError("candidate has not been submitted for review") from exc

    def activate(self, candidate: AbstractionCandidate, *, approval_id: str) -> CandidateReview:
        current = self.get(candidate)
        if current.decision != "APPROVED" or current.approval_id != approval_id:
            raise CandidateReviewError("candidate requires a matching approval")
        if current.activated:
            return current
        updated = CandidateReview(current.candidate, current.reviewer, current.evidence, current.decision, current.note, current.approval_id, current.decided_at, True)
        if self.storage is None:
            self._reviews[current.candidate.supporting_fallback_ids] = updated
            return updated

        # The review flag, deterministic registry transaction, and immutable
        # receipt share one SQLite writer transaction. No activated-only state
        # can survive an activation failure.
        def operation(conn):
            row = conn.execute(
                "SELECT decision, approval_id, activated FROM candidate_reviews WHERE candidate_key=?",
                (self._key(candidate),),
            ).fetchone()
            if row is None or row["decision"] != "APPROVED" or row["approval_id"] != approval_id:
                raise CandidateReviewError("candidate requires a matching durable approval")
            if row["activated"]:
                return
            now = datetime.now(timezone.utc).isoformat()
            candidate_key = self._key(candidate)
            activation_key = sha256(f"{candidate_key}|{approval_id}|{candidate.recommended_abstraction}".encode()).hexdigest()
            conn.execute(
                "INSERT OR IGNORE INTO abstraction_activation_registry (activation_key,candidate_key,abstraction_kind,canonical_function,enabled,activated_at) VALUES (?,?,?,?,?,?)",
                (activation_key, candidate_key, candidate.recommended_abstraction, candidate.canonical_function, int(candidate.recommended_abstraction != "NEW_LANE"), now),
            )
            conn.execute("UPDATE candidate_reviews SET activated=1, activation_status='ACTIVATED' WHERE candidate_key=?", (candidate_key,))
            conn.execute(
                "INSERT INTO candidate_activation_audit (audit_id,candidate_key,approval_id,actor,activated_at,activation_key) VALUES (?,?,?,?,?,?)",
                (activation_key, candidate_key, approval_id, current.reviewer, now, activation_key),
            )
        self.storage.write(operation)
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
        self._persist(updated)
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
