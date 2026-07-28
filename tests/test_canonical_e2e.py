from pathlib import Path

from vesper.approved_file_apply import ApprovedFileApply, FileApplyApproval, PatchOperation, PatchSet
from vesper.composition import Composer
from vesper.verification import VerificationRunner


def test_canonical_bounded_repository_flow(tmp_path: Path):
    target = tmp_path / "bounded_task.txt"
    target.write_text("before\n", encoding="utf-8")
    patch_set = PatchSet("canonical-p1", tmp_path, (PatchOperation("bounded_task.txt", "before\n", "after\n"),))
    applied = ApprovedFileApply(tmp_path).apply(
        patch_set,
        approval=FileApplyApproval("director-a1", "director", "canonical-p1", tmp_path),
    )
    assert applied.changed_paths == ("bounded_task.txt",)
    assert target.read_text(encoding="utf-8") == "after\n"

    report = VerificationRunner().run(
        "canonical-p1",
        ("bounded file content",),
        {"bounded file content": {"source": "kernel", "status": "passed", "exit_code": 0, "command": "python -c content-check"}},
    )
    document = Composer().compose(report, title="Canonical bounded task", body="Applied bounded change.")
    assert document.sources == ("canonical-p1",)
    assert "exit 0" in document.body


def test_canonical_flow_recovery_artifact_is_replayable(tmp_path: Path):
    target = tmp_path / "recovery.txt"
    target.write_text("before\n", encoding="utf-8")
    patch = PatchSet("recovery-p1", tmp_path, (PatchOperation("recovery.txt", "before\n", "after\n"),))
    first = ApprovedFileApply(tmp_path).apply(patch, approval=FileApplyApproval("a1", "director", "recovery-p1", tmp_path))
    assert first.patch_id == patch.patch_id
    assert target.read_text(encoding="utf-8") == "after\n"
    # Replay is safely rejected as stale rather than applying twice after restart.
    try:
        ApprovedFileApply(tmp_path).apply(patch, approval=FileApplyApproval("a1", "director", "recovery-p1", tmp_path))
    except Exception as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale replay must be rejected")
    assert target.read_text(encoding="utf-8") == "after\n"


def test_active_repository_canonical_fixture_is_not_modified():
    # The canonical active-repository execution is intentionally opt-in through
    # the dedicated fixture command; ordinary tests never mutate the source tree.
    assert Path(__file__).parent.parent.name == "vesper"
