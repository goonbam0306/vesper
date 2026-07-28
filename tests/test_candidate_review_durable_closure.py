from vesper.candidate_review import CandidateReviewStore
from vesper.fallbacks import AbstractionCandidate
from vesper.storage import Storage


def test_candidate_review_approval_survives_restart(tmp_path):
    db = tmp_path / "vesper.sqlite3"
    storage = Storage(db)
    storage.migrate()
    storage.start()
    candidate = AbstractionCandidate(("fb-1", "fb-2"), "research", "SKILL")
    review = CandidateReviewStore(storage)
    review.submit(candidate, reviewer="director", evidence=("verify:1",))
    approved = review.decide(candidate, reviewer="director", approved=True, note="stable")
    assert approved.approval_id is not None
    storage.stop()

    restarted = Storage(db)
    restarted.migrate()
    restarted.start()
    loaded = CandidateReviewStore(restarted).get(candidate)
    assert loaded.approval_id == approved.approval_id
    assert loaded.decision == "APPROVED"
    active = CandidateReviewStore(restarted).activate(candidate, approval_id=approved.approval_id)
    assert active.activated is True
    restarted.stop()


def test_candidate_review_requires_matching_approval(tmp_path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate()
    storage.start()
    candidate = AbstractionCandidate(("fb-3", "fb-4"), "research", "SKILL")
    store = CandidateReviewStore(storage)
    store.submit(candidate, reviewer="director", evidence=("verify:2",))
    try:
        store.activate(candidate, approval_id="wrong")
        raise AssertionError("expected CandidateReviewError")
    except ValueError:
        pass
    storage.stop()


if __name__ == "__main__":
    test_candidate_review_approval_survives_restart(__import__("pathlib").Path("/tmp"))
    test_candidate_review_requires_matching_approval(__import__("pathlib").Path("/tmp"))
