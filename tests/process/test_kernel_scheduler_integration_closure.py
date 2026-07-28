from datetime import datetime, timezone

from vesper.kernel import Kernel, ProcessExecutionOutcome, ProcessStatus, WaitReason
from vesper.process_policy import ProcessRecurrenceStore, ProcessTimerStore
from vesper.storage import Storage


def _kernel(tmp_path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate()
    storage.start()
    return storage, Kernel(storage)


def test_due_timer_is_claimed_woken_and_enqueued_by_kernel(tmp_path):
    storage, kernel = _kernel(tmp_path)
    process = kernel.submit("timer-test")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    kernel.wait(process.process_id, WaitReason.TIMER, wake_key="wake:p1")
    ProcessTimerStore(storage).schedule(process.process_id, "2026-01-01T00:00:00+00:00", wake_key="wake:p1")

    result = kernel.reconcile_scheduled_work(now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert result["timers"] == (process.process_id,)
    current = kernel.get(process.process_id)
    assert current is not None and current.status == ProcessStatus.RUNNING
    assert kernel.scheduler_metrics()["runnable_processes"] == 1
    storage.stop()


def test_due_recurrence_uses_kernel_scheduler_and_observes_run_limit(tmp_path):
    storage, kernel = _kernel(tmp_path)
    process = kernel.submit("recurrence-test")
    recurrence = ProcessRecurrenceStore(storage)
    recurrence.configure(process.process_id, interval_seconds=60, max_runs=1)
    recurrence.next_run(process.process_id, now="2026-01-01T00:00:00+00:00")
    kernel.register_handler(
        process.process_id,
        lambda _: ProcessExecutionOutcome(ProcessStatus.COMPLETED),
    )

    result = kernel.run_scheduler(max_slices=1, now=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc))

    assert result[0].process_id == process.process_id
    current = kernel.get(process.process_id)
    assert current is not None and current.status == ProcessStatus.COMPLETED
    assert ProcessRecurrenceStore(storage).next_run(process.process_id, now="2026-01-01T00:02:00+00:00") is None
    storage.stop()


def test_timer_claim_is_idempotent_after_reconciliation(tmp_path):
    storage, kernel = _kernel(tmp_path)
    process = kernel.submit("idempotent-timer")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    kernel.wait(process.process_id, WaitReason.TIMER, wake_key="wake:p2")
    ProcessTimerStore(storage).schedule(process.process_id, "2026-01-01T00:00:00+00:00", wake_key="wake:p2")

    first = kernel.reconcile_scheduled_work(now="2026-01-01T00:00:01+00:00")
    second = kernel.reconcile_scheduled_work(now="2026-01-01T00:00:02+00:00")

    assert first["timers"] == (process.process_id,)
    assert second["timers"] == ()
    storage.stop()


def test_recurrence_configure_requires_positive_bounds(tmp_path):
    storage, kernel = _kernel(tmp_path)
    process = kernel.submit("bounds-test")
    try:
        try:
            ProcessRecurrenceStore(storage).configure(process.process_id, interval_seconds=0, max_runs=1)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    finally:
        storage.stop()

