import pytest

from vesper.candidate_review import CandidateReviewError, CandidateReviewStore
from vesper.fallbacks import CandidateBuilder, FallbackRecord


def candidate():
    record = FallbackRecord("a", "research", ("analyze",), ("text",), ("text",), ("read",), ("quality",), ("read",))
    return CandidateBuilder().build((record, record))


def test_approval_has_immutable_receipt_and_explicit_activation():
    store = CandidateReviewStore()
    item = candidate()
    store.submit(item, reviewer="director", evidence=("stable",))
    approved = store.decide(item, reviewer="director", approved=True, note="pass")
    assert approved.approval_id
    assert approved.decided_at
    assert approved.activated is False
    activated = store.activate(item, approval_id=approved.approval_id)
    assert activated.activated is True
    assert store.activate(item, approval_id=approved.approval_id) == activated


def test_rejected_or_wrong_receipt_cannot_activate():
    store = CandidateReviewStore()
    item = candidate()
    store.submit(item, reviewer="director", evidence=("stable",))
    rejected = store.decide(item, reviewer="director", approved=False)
    with pytest.raises(CandidateReviewError):
        store.activate(item, approval_id=rejected.approval_id or "missing")
