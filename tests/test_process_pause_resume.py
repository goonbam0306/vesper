from vesper.kernel import Kernel, ProcessStatus
from vesper.storage import Storage


def test_process_pause_resume_is_durable(tmp_path):
    storage = Storage(tmp_path / "pause.db")
    storage.migrate(); storage.start()
    kernel = Kernel(storage)
    process = kernel.submit("test")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    paused = kernel.transition(process.process_id, ProcessStatus.PAUSED)
    assert paused.status == ProcessStatus.PAUSED
    restarted = Kernel(storage)
    resumed = restarted.transition(process.process_id, ProcessStatus.RUNNING)
    assert resumed.status == ProcessStatus.RUNNING