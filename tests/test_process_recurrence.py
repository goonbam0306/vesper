from vesper.process_policy import ProcessRecurrenceStore
from vesper.storage import Storage


def test_recurrence_is_bounded_and_reenqueued(tmp_path):
    storage = Storage(tmp_path / "recurrence.db")
    storage.migrate(); storage.start()
    storage.write(lambda c: c.execute("INSERT INTO processes(process_id,status,origin,created_at,updated_at) VALUES('p1','WAITING','test','now','now')"))
    store = ProcessRecurrenceStore(storage)
    store.configure("p1", interval_seconds=60, max_runs=2)
    assert store.next_run("p1", now="2026-01-01T00:00:00+00:00") == 1
    assert store.next_run("p1", now="2026-01-01T00:01:00+00:00") == 2
    assert store.next_run("p1", now="2026-01-01T00:02:00+00:00") is None