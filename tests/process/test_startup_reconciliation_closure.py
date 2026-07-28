from pathlib import Path

from vesper.api import Runtime
from vesper.kernel import ProcessStatus


def test_startup_reconciliation_pauses_uncertain_running_process(tmp_path: Path):
    first = Runtime(tmp_path)
    first.start()
    process = first.kernel.submit("crash-point", client_request_id="reconcile-1")
    first.kernel.transition(process.process_id, ProcessStatus.RUNNING)
    first.stop()

    second = Runtime(tmp_path)
    second.start()
    recovered = second.kernel.get(process.process_id)
    assert recovered is not None
    assert recovered.status == ProcessStatus.PAUSED.value
    assert second.kernel.reconcile_startup()["paused_uncertain"] == ()
    second.stop()


def test_startup_reconciliation_applies_durable_terminal_intent(tmp_path: Path):
    first = Runtime(tmp_path)
    first.start()
    process = first.kernel.submit("terminal-point", client_request_id="reconcile-2")
    first.kernel.transition(process.process_id, ProcessStatus.RUNNING)
    first.kernel.result(process.process_id, {"ok": True})
    first.stop()

    second = Runtime(tmp_path)
    second.start()
    recovered = second.kernel.get(process.process_id)
    assert recovered is not None
    assert recovered.status == ProcessStatus.COMPLETED.value
    second.stop()
