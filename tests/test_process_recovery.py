from vesper.kernel import Kernel, ProcessStatus
from vesper.storage import Storage


def test_recover_running_processes_pauses_durably(tmp_path):
    storage = Storage(tmp_path / "recovery.db")
    storage.migrate(); storage.start()
    kernel = Kernel(storage)
    process = kernel.submit("test")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    recovered = kernel.recover_running_processes()
    assert recovered == (process.process_id,)
    assert kernel.get(process.process_id).status == ProcessStatus.PAUSED