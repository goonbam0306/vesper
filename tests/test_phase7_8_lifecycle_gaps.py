from datetime import datetime, timezone

from vesper.process_policy import ProcessPolicy, ProcessPolicyStore
from vesper.storage import Storage


def test_process_policy_class_and_pause_resume_are_durable(tmp_path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    storage.write(lambda c: c.execute(
        "INSERT INTO processes(process_id,status,origin,created_at,updated_at) VALUES(?,?,?,?,?)",
        ("p1", "RUNNING", "test", "now", "now"),
    ))
    store = ProcessPolicyStore(storage)
    policy = store.create(ProcessPolicy(process_id="p1", policy_class="monitoring"))
    assert policy.policy_class == "monitoring"
    assert store.pause("p1") == "PAUSED"
    assert store.resume("p1") == "RUNNING"
    assert store.get("p1").policy_class == "monitoring"
    storage.stop()


def test_policy_class_is_restricted(tmp_path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        ProcessPolicy(process_id="p1", policy_class="unknown")
    except ValueError as exc:
        assert "policy_class" in str(exc)
    else:
        raise AssertionError("invalid policy class accepted")
    storage.stop()
