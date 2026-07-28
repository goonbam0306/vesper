from vesper.process_policy import ProcessPolicy, ProcessPolicyStore, ProcessRecurrenceStore
from vesper.storage import Storage


def test_interactive_and_recurring_processes_share_policy_and_recovery_path(tmp_path):
    storage = Storage(tmp_path / "fel.db")
    storage.migrate()
    storage.start()
    for pid, policy_class in (("interactive", "interactive"), ("recurring", "recurring")):
        storage.write(lambda c, pid=pid: c.execute(
            "INSERT INTO processes(process_id,status,origin,created_at,updated_at) VALUES(?,?,?,?,?)",
            (pid, "RUNNING", "gate", "now", "now"),
        ))
        ProcessPolicyStore(storage).create(ProcessPolicy(pid, policy_class=policy_class))
    recurrence = ProcessRecurrenceStore(storage)
    recurrence.configure("recurring", interval_seconds=60, max_runs=1)
    assert recurrence.next_run("recurring", now="2026-01-01T00:00:00+00:00") == 1
    recovered = ProcessPolicyStore(storage).recover_after_crash()
    assert recovered == ("interactive", "recurring")
    rows = storage.write(lambda c: c.execute(
        "SELECT process_id,status,revision FROM processes WHERE process_id IN ('interactive','recurring') ORDER BY process_id"
    ).fetchall())
    assert [(r["process_id"], r["status"], r["revision"]) for r in rows] == [
        ("interactive", "PAUSED", 1), ("recurring", "PAUSED", 1)
    ]
    storage.stop()


def test_policy_limits_are_common_for_short_and_long_lived_classes():
    interactive = ProcessPolicy("i", policy_class="interactive", max_graph_nodes=2)
    recurring = ProcessPolicy("r", policy_class="recurring", max_graph_nodes=2)
    for policy in (interactive, recurring):
        assert policy.allows_graph(nodes=2, depth=1, lane_invocations=1, replans=1, retries=1)
        assert not policy.allows_graph(nodes=3, depth=1, lane_invocations=1, replans=1, retries=1)
        assert policy.requires_approval("external_write") is False
        assert policy.requires_approval("dangerous") is False


def test_policy_approval_boundary_is_shared():
    for policy_class in ("interactive", "recurring", "monitoring"):
        policy = ProcessPolicy("p", policy_class=policy_class, approval_boundaries=("external_write",))
        assert policy.requires_approval("external_write")
        assert not policy.requires_approval("read")
