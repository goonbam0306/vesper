from datetime import datetime, timezone

from vesper.kernel import Kernel, ProcessExecutionOutcome, ProcessStatus, WaitReason
from vesper.process_policy import ProcessTimerStore
from vesper.storage import Storage


def test_timer_wake_executes_origin_handler_through_scheduler(tmp_path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    kernel = Kernel(storage)
    calls = []
    kernel.register_origin_handler("timer-runtime", lambda pid: (calls.append(pid) or ProcessExecutionOutcome(ProcessStatus.COMPLETED)))
    process = kernel.submit("timer-runtime")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    kernel.wait(process.process_id, WaitReason.TIMER, wake_key="runtime:wake")
    ProcessTimerStore(storage).schedule(process.process_id, "2026-01-01T00:00:00+00:00", wake_key="runtime:wake")

    result = kernel.run_scheduler(max_slices=1, now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert [p.process_id for p in result] == [process.process_id]
    assert calls == [process.process_id]
    assert kernel.get(process.process_id).status == ProcessStatus.COMPLETED
    storage.stop()


def test_paused_recurrence_executes_through_scheduler(tmp_path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    kernel = Kernel(storage)
    calls = []
    kernel.register_origin_handler("recurring-runtime", lambda pid: (calls.append(pid) or ProcessExecutionOutcome(ProcessStatus.COMPLETED)))
    process = kernel.submit("recurring-runtime")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    kernel.transition(process.process_id, ProcessStatus.PAUSED)
    storage.write(lambda c: c.execute("INSERT INTO process_recurrences(process_id,interval_seconds,max_runs,run_count,next_due_at) VALUES(?,?,?,?,?)", (process.process_id, 60, 1, 0, "2026-01-01T00:00:00+00:00")))

    kernel.run_scheduler(max_slices=1, now="2026-01-01T00:00:01+00:00")

    assert calls == [process.process_id]
    assert kernel.get(process.process_id).status == ProcessStatus.COMPLETED
    storage.stop()


def test_scheduler_without_handler_is_not_reported_as_execution(tmp_path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    kernel = Kernel(storage)
    process = kernel.submit("no-handler")
    result = kernel.run_scheduler(max_slices=1)
    assert [p.process_id for p in result] == [process.process_id]
    assert kernel.get(process.process_id).status == ProcessStatus.RUNNING
    storage.stop()


__all__ = []
