from vesper.process_policy import ProcessPolicy, ProcessPolicyStore
from vesper.storage import Storage


def test_recover_after_service_crash_requeues_running_process(tmp_path):
    storage = Storage(tmp_path / "recovery.db")
    storage.migrate()
    storage.start()
    storage.write(lambda c: c.execute("INSERT INTO processes(process_id,status,origin,created_at,updated_at) VALUES('p1','RUNNING','test','now','now')"))
    store = ProcessPolicyStore(storage)
    store.create(ProcessPolicy("p1", policy_class="persistent"))
    assert store.recover_after_crash() == ("p1",)
    row = storage.write(lambda c: c.execute("SELECT status FROM processes WHERE process_id='p1'").fetchone())
    assert row["status"] == "PAUSED"
    storage.stop()


def test_recovery_ignores_terminal_processes(tmp_path):
    storage = Storage(tmp_path / "recovery.db")
    storage.migrate()
    storage.start()
    storage.write(lambda c: c.execute("INSERT INTO processes(process_id,status,origin,created_at,updated_at) VALUES('p1','COMPLETED','test','now','now')"))
    store = ProcessPolicyStore(storage)
    store.create(ProcessPolicy("p1"))
    assert store.recover_after_crash() == ()
    storage.stop()
