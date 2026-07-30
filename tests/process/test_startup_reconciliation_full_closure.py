from datetime import datetime, timezone

from vesper.api import Runtime
from vesper.kernel import ProcessStatus
from vesper.process_policy import ProcessBudget, ProcessPolicy, ProcessPolicyStore, ProcessRecurrenceStore, ProcessTimerStore


def test_runtime_start_reconciles_all_applicable_durable_state(tmp_path):
    first = Runtime(tmp_path)
    first.start()
    process = first.kernel.submit("monitoring-runtime")
    first.kernel.transition(process.process_id, ProcessStatus.RUNNING)
    ProcessBudget.load(first.storage, process.process_id, default_tokens=10, default_seconds=20).consume(tokens=3, seconds=4)
    ProcessPolicyStore(first.storage).create(ProcessPolicy(process.process_id, policy_class="monitoring"))
    ProcessRecurrenceStore(first.storage).configure(process.process_id, interval_seconds=60, max_runs=2)
    ProcessTimerStore(first.storage).schedule(process.process_id, "2026-01-01T00:00:00+00:00", wake_key="reconcile:wake")
    first.stop()

    second = Runtime(tmp_path)
    second.start()
    report = second.startup_reconciliation

    assert second.kernel.get(process.process_id).status == ProcessStatus.PAUSED
    assert process.process_id in report["paused_uncertain"]
    assert process.process_id in report["recurring_processes"]
    assert process.process_id in report["monitoring_processes"]
    assert process.process_id in report["policy_runtime_state"]
    assert process.process_id in report["claimed_timers_released"]
    budget = ProcessBudget.load(second.storage, process.process_id, default_tokens=99, default_seconds=99)
    assert (budget.tokens, budget.seconds) == (7, 16)
    second.stop()


def test_startup_does_not_complete_unknown_graph_wait_or_effect(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.start()
    process = runtime.kernel.submit("uncertain")
    runtime.kernel.transition(process.process_id, ProcessStatus.RUNNING)
    now = datetime.now(timezone.utc).isoformat()
    runtime.storage.write(lambda c: (
        c.execute("INSERT INTO execution_graphs(graph_id,process_id,created_at,updated_at) VALUES(?,?,?,?)", ("g1", process.process_id, now, now)),
        c.execute("INSERT INTO execution_graph_nodes(graph_id,node_id,node_type,status,dependencies_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", ("g1", "n1", "LANE", "RUNNING", "[]", now, now)),
        c.execute("INSERT INTO execution_graph_waits(graph_id,node_id,wait_key,created_at) VALUES(?,?,?,?)", ("g1", "n1", "wait:1", now)),
        c.execute("INSERT INTO effects(effect_id,process_id,operation,fingerprint,status) VALUES(?,?,?,?,?)", ("e1", process.process_id, "test.echo", "fp", "UNKNOWN_EFFECT")),
    ))
    runtime.stop()

    recovered = Runtime(tmp_path)
    recovered.start()
    report = recovered.startup_reconciliation
    assert process.process_id in report["paused_uncertain"]
    assert "g1:n1" in report["running_graph_nodes"]
    assert "g1:n1" in report["open_waits"]
    assert "e1" in report["unreconciled_effects"]
    assert recovered.kernel.get(process.process_id).status == ProcessStatus.PAUSED
    recovered.stop()


__all__ = []
