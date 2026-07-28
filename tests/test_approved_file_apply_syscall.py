import json
from pathlib import Path

import pytest

from vesper.approved_file_apply import FileApplyApproval, PatchOperation, PatchSet
from vesper.kernel import Kernel
from vesper.storage import Storage
from vesper.syscalls import ApprovalDecision, Decision, SyscallEngine, SyscallRequest


def test_approved_file_apply_is_a_kernel_authorized_syscall(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite3")
    storage.migrate()
    storage.start()
    try:
        kernel = Kernel(storage)
        process = kernel.submit("apply", volatile=False)
        engine = SyscallEngine(storage, kernel, repository_root=tmp_path)
        engine.register("approved_file_apply", "kernel", {"required": ["patch_id", "repository_root", "operations"]}, "WRITE", "EXPOSED")
        engine.grant(operation="approved_file_apply", resource_selector=str(tmp_path), decision=Decision.ASK)
        target = tmp_path / "file.txt"
        target.write_text("old\n", encoding="utf-8")
        request = SyscallRequest(
            process_id=process.process_id,
            operation="approved_file_apply",
            target=str(tmp_path),
            args={
                "patch_id": "p1",
                "repository_root": str(tmp_path),
                "operations": [{"path": "file.txt", "old_text": "old\n", "new_text": "new\n"}],
            },
        )
        approval_id = engine.request_approval(request)
        engine.decide(approval_id, ApprovalDecision.APPROVED)
        result = engine.execute(request, approval_id=approval_id)
        assert result.status == "COMMITTED"
        assert target.read_text(encoding="utf-8") == "new\n"
    finally:
        storage.stop()


def test_file_apply_syscall_rejects_repository_mismatch(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite3")
    storage.migrate()
    storage.start()
    try:
        kernel = Kernel(storage)
        process = kernel.submit("apply", volatile=False)
        engine = SyscallEngine(storage, kernel, repository_root=tmp_path)
        engine.register("approved_file_apply", "kernel", {"required": ["patch_id", "repository_root", "operations"]}, "WRITE", "EXPOSED")
        engine.grant(operation="approved_file_apply", resource_selector=str(tmp_path), decision=Decision.ALLOW)
        request = SyscallRequest(process.process_id, "approved_file_apply", str(tmp_path), {
            "patch_id": "p2", "repository_root": str(tmp_path.parent), "operations": []
        })
        with pytest.raises(Exception):
            engine.execute(request)
    finally:
        storage.stop()


def _unused_serialization_reference():
    return json.dumps(FileApplyApproval("a", "d", "p", Path("/tmp" )).__dict__)


def _unused_patch_reference():
    return PatchSet("p", Path("/tmp"), (PatchOperation("x", "", ""),))


def _unused_json():
    return json.loads("{}")
