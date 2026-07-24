"""Kernel-owned content-addressed artifact publication."""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import artifact_root, artifact_staging, ensure_runtime_dirs
from .storage import Storage


class ArtifactCommitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    path: Path
    byte_size: int
    media_type: str | None = None


class ArtifactStore:
    def __init__(self, home: Path, storage: Storage) -> None:
        if not isinstance(storage, Storage):
            raise TypeError("ArtifactStore requires the canonical Storage writer")
        self.home = home.resolve()
        ensure_runtime_dirs(self.home)
        self.root = artifact_root(self.home)
        self.staging = artifact_staging(self.home)
        self.content_root = self.root / "sha256"
        self.content_root.mkdir(parents=True, exist_ok=True)
        self.storage = storage

    def _path(self, digest: str) -> Path:
        return self.content_root / digest[:2] / digest[2:]

    def publish(
        self,
        data: bytes,
        *,
        media_type: str | None = None,
        fault: Literal["after_rename_before_db", "before_db_commit"] | None = None,
    ) -> Artifact:
        digest = hashlib.sha256(data).hexdigest()
        artifact_id = f"sha256:{digest}"
        destination = self._path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix="artifact-", dir=self.staging)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # Hash is computed from the staged bytes, not trusted input metadata.
            with temporary.open("rb") as handle:
                verified = hashlib.sha256(handle.read()).hexdigest()
            if verified != digest:
                raise ArtifactCommitError("staged artifact hash mismatch")
            os.replace(temporary, destination)
            self._fsync_directory(destination.parent)
            artifact = Artifact(artifact_id, destination, len(data), media_type)
            if fault == "after_rename_before_db":
                raise ArtifactCommitError("fault injected after atomic rename")

            def commit(conn):
                conn.execute(
                    "INSERT OR IGNORE INTO artifacts(artifact_id, sha256, byte_size, media_type, path) VALUES (?, ?, ?, ?, ?)",
                    (artifact_id, digest, len(data), media_type, str(destination)),
                )
                return artifact

            if fault == "before_db_commit":
                raise ArtifactCommitError("fault injected before database commit")
            return self.storage.write(commit)
        except ArtifactCommitError:
            raise
        except Exception as exc:
            raise ArtifactCommitError(str(exc)) from exc
        finally:
            temporary.unlink(missing_ok=True)

    def reconcile(self) -> int:
        """Publish valid renamed orphan bytes; never creates DB refs to missing bytes."""
        repaired = 0
        for candidate in self._content_files():
            digest = candidate.parent.name + candidate.name
            artifact_id = f"sha256:{digest}"
            if len(digest) != 64 or not self._valid_digest(candidate, digest):
                continue
            if self.storage.connect().execute("SELECT 1 FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone():
                continue
            size = candidate.stat().st_size
            self.storage.write(lambda conn, aid=artifact_id, d=digest, s=size, p=candidate: conn.execute(
                "INSERT OR IGNORE INTO artifacts(artifact_id, sha256, byte_size, path) VALUES (?, ?, ?, ?)",
                (aid, d, s, str(p)),
            ))
            repaired += 1
        return repaired

    def cleanup_orphans(self) -> int:
        referenced = {row[0] for row in self.storage.connect().execute("SELECT path FROM artifacts")}
        removed = 0
        for candidate in self._content_files():
            if str(candidate) not in referenced:
                candidate.unlink(missing_ok=True)
                removed += 1
        return removed

    def _content_files(self):
        return (p for p in self.content_root.glob("??/*") if p.is_file())

    @staticmethod
    def _valid_digest(path: Path, expected: str) -> bool:
        with path.open("rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest() == expected

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
