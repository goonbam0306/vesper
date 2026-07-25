from vesper.kernel import Kernel, ProcessExecutionOutcome, ProcessStatus
from vesper.storage import Storage


def test_terminal_intent_recovery_ignores_application_output_status(tmp_path):
    storage = Storage(tmp_path / "db.sqlite3")
    storage.migrate()
    storage.start()
    kernel = Kernel(storage)
    cases = [(ProcessStatus.COMPLETED, "ACTION_FAILED", ProcessStatus.COMPLETED), (ProcessStatus.FAILED, "MODEL_READY", ProcessStatus.FAILED)]
    for intent, application_status, expected in cases:
        process = kernel.submit("test", volatile=False)
        kernel.transition(process.process_id, ProcessStatus.RUNNING)
        kernel.result(process.process_id, {"status": application_status}, terminal_status=intent)
        recovered = kernel.recover_terminal_intents()
        assert recovered[0].status == expected
        assert storage.write(lambda c, pid=process.process_id: c.execute("SELECT COUNT(*) FROM process_results WHERE process_id=?", (pid,)).fetchone()[0]) == 1
    storage.stop()


def test_scheduler_uses_generic_terminal_status_not_application_status(tmp_path):
    storage = Storage(tmp_path / "db.sqlite3")
    storage.migrate()
    storage.start()
    kernel = Kernel(storage)
    p = kernel.submit("test", volatile=False)
    kernel.register_handler(p.process_id, lambda _: ProcessExecutionOutcome(
        ProcessStatus.COMPLETED, {"status": "UNKNOWN_APPLICATION_STATUS"}
    ))
    kernel.run_scheduler(max_slices=1)
    assert kernel.get(p.process_id).status == ProcessStatus.COMPLETED
    q = kernel.submit("test", volatile=False)
    kernel.register_handler(q.process_id, lambda _: ProcessExecutionOutcome(
        ProcessStatus.FAILED, {"status": "MODEL_READY"}
    ))
    kernel.run_scheduler(max_slices=1)
    assert kernel.get(q.process_id).status == ProcessStatus.FAILED
    storage.stop()
