"""Kernel-controlled, approval-gated bounded file application."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


class FileApplyError(RuntimeError):
    """The approved patch could not be safely applied."""


@dataclass(frozen=True)
class PatchOperation:
    path: str
    old_text: str
    new_text: str


@dataclass(frozen=True)
class PatchSet:
    patch_id: str
    repository_root: Path
    operations: tuple[PatchOperation, ...]


@dataclass(frozen=True)
class FileApplyApproval:
    approval_id: str
    director_id: str
    patch_id: str
    repository_root: Path


@dataclass(frozen=True)
class ApplyResult:
    patch_id: str
    approval_id: str
    changed_paths: tuple[str, ...]


class ApprovedFileApply:
    """Apply a bounded PatchSet only after an explicit Director approval."""

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()
        if not self.repository_root.is_dir():
            raise FileApplyError("repository root must be an existing directory")

    def apply(self, patch_set: PatchSet, *, approval: FileApplyApproval | None) -> ApplyResult:
        if approval is None:
            raise FileApplyError("Director approval is required")
        root = patch_set.repository_root.resolve()
        if root != self.repository_root:
            raise FileApplyError("patch repository does not match active repository")
        if approval.patch_id != patch_set.patch_id or approval.repository_root.resolve() != root:
            raise FileApplyError("approval does not authorize this PatchSet")
        if not approval.approval_id or not approval.director_id:
            raise FileApplyError("approval identity is required")
        if not patch_set.operations:
            raise FileApplyError("PatchSet must contain at least one operation")

        prepared: list[tuple[Path, str, Path, Path]] = []
        seen: set[Path] = set()
        temporary_dir = Path(tempfile.mkdtemp(prefix="vesper-apply-", dir=root))
        try:
            for operation in patch_set.operations:
                destination = self._safe_path(operation.path)
                if destination in seen:
                    raise FileApplyError(f"duplicate patch path: {operation.path}")
                seen.add(destination)
                if not destination.is_file():
                    raise FileApplyError(f"target file does not exist: {operation.path}")
                current = destination.read_text(encoding="utf-8")
                if current != operation.old_text:
                    raise FileApplyError(f"stale patch content: {operation.path}")
                temporary = temporary_dir / str(len(prepared))
                temporary.write_text(operation.new_text, encoding="utf-8")
                backup = temporary_dir / f"backup-{len(prepared)}"
                backup.write_bytes(destination.read_bytes())
                prepared.append((destination, operation.path, temporary, backup))

            replaced: list[tuple[Path, Path]] = []
            try:
                for destination, _, temporary, backup in prepared:
                    os.replace(temporary, destination)
                    replaced.append((destination, backup))
            except OSError as exc:
                for destination, backup in reversed(replaced):
                    os.replace(backup, destination)
                raise FileApplyError(str(exc)) from exc
            return ApplyResult(patch_set.patch_id, approval.approval_id, tuple(item[1] for item in prepared))
        except FileApplyError:
            raise
        except (OSError, UnicodeError) as exc:
            raise FileApplyError(str(exc)) from exc
        finally:
            for item in temporary_dir.iterdir():
                item.unlink(missing_ok=True)
            temporary_dir.rmdir()

    def _safe_path(self, relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise FileApplyError("patch paths must be non-empty relative paths")
        candidate = (self.repository_root / relative_path).resolve()
        try:
            candidate.relative_to(self.repository_root)
        except ValueError as exc:
            raise FileApplyError("patch path escapes active repository") from exc
        return candidate
