from vesper.candidate_review import CandidateReviewStore
from vesper.fallbacks import AbstractionCandidate
from vesper.storage import Storage


def test_activation_requires_approval_and_writes_audit(tmp_path):
    db = tmp_path / "vesper.sqlite3"
    storage = Storage(db)
    storage.migrate()
    storage.start()
    candidate = AbstractionCandidate(("fb-a", "fb-b"), "research", "SKILL")
    store = CandidateReviewStore(storage)
    store.submit(candidate, reviewer="director", evidence=("proof",))
    try:
        store.activate(candidate, approval_id="not-approved")
        raise AssertionError("activation should require approval")
    except ValueError:
        pass
    approved = store.decide(candidate, reviewer="director", approved=True)
    assert approved.approval_id is not None
    active = store.activate(candidate, approval_id=approved.approval_id)
    assert active.activated is True
    row = storage.connect().execute(
        "SELECT COUNT(*) AS count FROM candidate_activation_audit WHERE candidate_key = ?",
        (store._key(candidate),),
    ).fetchone()
    assert row["count"] == 1
    assert len(store.list()) == 1
    storage.stop()
