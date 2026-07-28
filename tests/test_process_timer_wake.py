from datetime import datetime, timedelta, timezone

from vesper.process_policy import ProcessTimerStore
from vesper.storage import Storage


def test_timer_wake_is_durable_and_due(tmp_path):
    storage = Storage(tmp_path / "timer.db")
    storage.migrate(); storage.start()
    storage.write(lambda c: c.execute("INSERT INTO processes(process_id,status,origin,created_at,updated_at) VALUES('p1','WAITING','test','now','now')"))
    store = ProcessTimerStore(storage)
    due= (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    store.schedule("p1", due, wake_key="timer:p1")
    assert store.due(now=datetime.now(timezone.utc)) == (("p1", "timer:p1"),)
    assert store.claim("p1") is True
    assert store.claim("p1") is False