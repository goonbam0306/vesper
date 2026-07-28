import pytest

from vesper.candidate_review import CandidateReviewError, CandidateReviewStore
from vesper.fallbacks import CandidateBuilder, FallbackRecord


def candidate():
    record = FallbackRecord("a", "research", ("analyze",), ("text",), ("text",), ("read",), ("quality",), ("read",))
    return CandidateBuilder().build((record, record))


def test_candidate_review_requires_evidence_and_preserves_pending_state():
    store = CandidateReviewStore()
    with pytest.raises(CandidateReviewError):
        store.submit(candidate(), reviewer="director", evidence=())
    review = store.submit(candidate(), reviewer="director", evidence=("fallback:a", "fallback:b"))
    assert review.decision == "PENDING"
    assert review.candidate.activation_status == "PENDING_DIRECTOR_APPROVAL"


def test_only_reviewer_can_approve_and_approval_does_not_activate_candidate():
    store = CandidateReviewStore()
    item = candidate()
    store.submit(item, reviewer="director", evidence=("cluster-stable",))
    with pytest.raises(CandidateReviewError):
        store.decide(item, reviewer="other", approved=True)
    approved = store.decide(item, reviewer="director", approved=True, note="meets contract")
    assert approved.decision == "APPROVED"
    assert approved.candidate.activation_status == "PENDING_DIRECTOR_APPROVAL"
