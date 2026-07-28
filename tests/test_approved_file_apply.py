from pathlib import Path

import pytest

from vesper.approved_file_apply import (
    ApprovedFileApply,
    FileApplyApproval,
    FileApplyError,
    PatchOperation,
    PatchSet,
)


def test_apply_requires_director_approval_and_stays_inside_repository(tmp_path: Path):
    target = tmp_path / "target.txt"
    target.write_text("before\n", encoding="utf-8")
    patch_set = PatchSet(
        patch_id="patch-1",
        repository_root=tmp_path,
        operations=(PatchOperation(path="target.txt", old_text="before\n", new_text="after\n"),),
    )
    applier = ApprovedFileApply(tmp_path)
    with pytest.raises(FileApplyError):
        applier.apply(patch_set, approval=None)
    result = applier.apply(
        patch_set,
        approval=FileApplyApproval(
            approval_id="approval-1",
            director_id="director",
            patch_id="patch-1",
            repository_root=tmp_path,
        ),
    )
    assert result.changed_paths == ("target.txt",)
    assert target.read_text(encoding="utf-8") == "after\n"


def test_apply_rejects_path_escape_and_stale_content(tmp_path: Path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    applier = ApprovedFileApply(tmp_path)
    escaping = PatchSet(
        patch_id="patch-escape",
        repository_root=tmp_path,
        operations=(PatchOperation(path="../outside.txt", old_text="secret\n", new_text="changed\n"),),
    )
    approval = FileApplyApproval("approval-escape", "director", "patch-escape", tmp_path)
    with pytest.raises(FileApplyError):
        applier.apply(escaping, approval=approval)
    target = tmp_path / "target.txt"
    target.write_text("actual\n", encoding="utf-8")
    stale = PatchSet("patch-stale", tmp_path, (PatchOperation("target.txt", "expected\n", "new\n"),))
    with pytest.raises(FileApplyError):
        applier.apply(stale, approval=FileApplyApproval("approval-stale", "director", "patch-stale", tmp_path))
    assert outside.read_text(encoding="utf-8") == "secret\n"
    assert target.read_text(encoding="utf-8") == "actual\n"


def test_apply_is_atomic_on_multi_file_failure(tmp_path: Path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one\n", encoding="utf-8")
    second.write_text("two\n", encoding="utf-8")
    patch_set = PatchSet(
        "patch-atomic",
        tmp_path,
        (
            PatchOperation("first.txt", "one\n", "ONE\n"),
            PatchOperation("second.txt", "wrong\n", "TWO\n"),
        ),
    )
    with pytest.raises(FileApplyError):
        ApprovedFileApply(tmp_path).apply(
            patch_set,
            approval=FileApplyApproval("approval-atomic", "director", "patch-atomic", tmp_path),
        )
    assert first.read_text(encoding="utf-8") == "one\n"
    assert second.read_text(encoding="utf-8") == "two\n"
