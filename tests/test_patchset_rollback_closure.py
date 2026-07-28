from pathlib import Path

import pytest

import vesper.approved_file_apply as module
from vesper.approved_file_apply import ApprovedFileApply, FileApplyApproval, FileApplyError, PatchOperation, PatchSet


def test_multi_file_replace_failure_rolls_back_completed_files(tmp_path: Path, monkeypatch):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one\n", encoding="utf-8")
    second.write_text("two\n", encoding="utf-8")
    original_replace = module.os.replace
    calls = {"count": 0}

    def fail_second(source, destination):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected replace failure")
        return original_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_second)
    patch = PatchSet("rollback", tmp_path, (
        PatchOperation("first.txt", "one\n", "ONE\n"),
        PatchOperation("second.txt", "two\n", "TWO\n"),
    ))
    with pytest.raises(FileApplyError, match="injected"):
        ApprovedFileApply(tmp_path).apply(patch, approval=FileApplyApproval("a", "director", "rollback", tmp_path))
    assert first.read_text(encoding="utf-8") == "one\n"
    assert second.read_text(encoding="utf-8") == "two\n"
