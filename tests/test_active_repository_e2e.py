from pathlib import Path

from vesper.composition import Composer
from vesper.kernel import Kernel
from vesper.storage import Storage
from vesper.syscalls import ApprovalDecision, Decision, SyscallEngine, SyscallRequest
from vesper.verification import VerificationRunner


def test_active_repository_readme_apply_verify_compose_and_restore():
    root = Path(__file__).resolve().parents[1]
    readme = root / "README.md"
    original = readme.read_text(encoding="utf-8")
    marker = "\n<!-- vesper-canonical-e2e -->\n"
    assert marker not in original

    storage = Storage(root / ".vesper-active-e2e.sqlite3")
    storage.migrate()
    storage.start()
    try:
        kernel = Kernel(storage)
        process = kernel.submit("active-repository-e2e", volatile=False)
        engine = SyscallEngine(storage, kernel, repository_root=root)
        engine.register("approved_file_apply", "kernel", {"required": ["patch_id", "repository_root", "operations"]}, "WRITE", "EXPOSED")
        engine.grant(operation="approved_file_apply", resource_selector=str(root), decision=Decision.ASK)
        request = SyscallRequest(
            process_id=process.process_id,
            operation="approved_file_apply",
            target=str(root),
            args={
                "patch_id": "active-readme-e2e",
                "repository_root": str(root),
                "operations": [{"path": "README.md", "old_text": original, "new_text": original + marker}],
            },
        )
        approval_id = engine.request_approval(request)
        engine.decide(approval_id, ApprovalDecision.APPROVED)
        result = engine.execute(request, approval_id=approval_id)
        assert result.status == "COMMITTED"
        assert marker in readme.read_text(encoding="utf-8")

        report = VerificationRunner().run(
            "active-readme-e2e",
            ("readme marker",),
            {"readme marker": {"source": "kernel", "status": "passed", "exit_code": 0, "command": "marker-check"}},
        )
        document = Composer().compose(report, title="Active README E2E", body="Bounded README change verified.")
        assert document.sources == ("active-readme-e2e",)
    finally:
        readme.write_text(original, encoding="utf-8")
        storage.stop()
        (root / ".vesper-active-e2e.sqlite3").unlink(missing_ok=True)
        (root / ".vesper-active-e2e.sqlite3-shm").unlink(missing_ok=True)
        (root / ".vesper-active-e2e.sqlite3-wal").unlink(missing_ok=True)

    assert readme.read_text(encoding="utf-8") == original
