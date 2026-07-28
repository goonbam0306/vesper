from vesper.kernel import Kernel, ProcessStatus
from vesper.storage import Storage


def test_active_process_recovery_survives_kernel_restart(tmp_path):
    db = tmp_path / "restart.db"
    first = Storage(db)
    first.migrate()
    first.start()
    kernel = Kernel(first)
    process = kernel.submit(origin="daily-research")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    first.stop()

    second = Storage(db)
    second.start()
    recovered_kernel = Kernel(second)
    recovered = recovered_kernel.recover_running_processes()
    assert recovered == (process.process_id,)
    restored = recovered_kernel.get(process.process_id)
    assert restored is not None
    assert restored.status == ProcessStatus.PAUSED
    assert restored.revision == 2
    second.stop()


def test_recovery_does_not_claim_completion(tmp_path):
    storage = Storage(tmp_path / "restart.db")
    storage.migrate()
    storage.start()
    kernel = Kernel(storage)
    process = kernel.submit(origin="daily-research")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    assert kernel.recover_running_processes() == (process.process_id,)
    assert kernel.get(process.process_id).status == ProcessStatus.PAUSED
    storage.stop()
