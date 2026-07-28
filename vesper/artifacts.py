"""Kernel-owned content-addressed artifact publication."""
from __future__ import annotations

import hashlib
import os
import tempfile
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .config import artifact_root, artifact_staging, ensure_runtime_dirs
from .storage import Storage


class ArtifactCommitError(RuntimeError):
    pass


class ArtifactValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    path: Path
    byte_size: int
    media_type: str | None = None


@dataclass(frozen=True)
class ArtifactEnvelope:
    artifact_id: str
    artifact_type: str
    schema_version: int
    process_id: str
    producer_invocation_id: str
    created_at: str
    provenance: dict
    content: dict


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

    def publish_typed(
        self,
        *,
        artifact_type: str,
        schema_version: int,
        process_id: str,
        producer_invocation_id: str,
        provenance: dict,
        content: dict,
    ) -> ArtifactEnvelope:
        if not isinstance(artifact_type, str) or not artifact_type.strip():
            raise ArtifactValidationError("artifact_type is required")
        if not isinstance(schema_version, int) or schema_version < 1:
            raise ArtifactValidationError("schema_version must be positive")
        if not process_id or not producer_invocation_id:
            raise ArtifactValidationError("process and producer identity are required")
        if not isinstance(provenance, dict) or not isinstance(content, dict):
            raise ArtifactValidationError("provenance and content must be objects")
        source_refs = provenance.get("source_refs", [])
        if not isinstance(source_refs, list) or not all(isinstance(ref, str) and ref for ref in source_refs):
            raise ArtifactValidationError("provenance.source_refs must be a list of non-empty references")
        created_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps({"artifact_type": artifact_type, "schema_version": schema_version, "process_id": process_id, "producer_invocation_id": producer_invocation_id, "created_at": created_at, "provenance": provenance, "content": content}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        artifact = self.publish(payload, media_type="application/vnd.vesper.artifact+json")
        envelope = ArtifactEnvelope(artifact.artifact_id, artifact_type, schema_version, process_id, producer_invocation_id, created_at, provenance, content)
        self.storage.write(lambda conn: conn.execute("INSERT INTO typed_artifacts (artifact_id, artifact_type, schema_version, process_id, producer_invocation_id, created_at, provenance_json, content_json) VALUES (?,?,?,?,?,?,?,?)", (artifact.artifact_id, artifact_type, schema_version, process_id, producer_invocation_id, created_at, json.dumps(provenance, sort_keys=True), json.dumps(content, sort_keys=True))))
        return envelope

    def load_typed(self, artifact_id: str, *, expected_type: str | None = None) -> ArtifactEnvelope:
        row = self.storage.connect().execute("SELECT artifact_id, artifact_type, schema_version, process_id, producer_invocation_id, created_at, provenance_json, content_json FROM typed_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise ArtifactValidationError(f"unknown typed artifact: {artifact_id}")
        if expected_type is not None and row["artifact_type"] != expected_type:
            raise ArtifactValidationError(f"artifact type mismatch: expected {expected_type}, got {row['artifact_type']}")
        return ArtifactEnvelope(row["artifact_id"], row["artifact_type"], row["schema_version"], row["process_id"], row["producer_invocation_id"], row["created_at"], json.loads(row["provenance_json"]), json.loads(row["content_json"]))

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

    def safe_export(self, destination: Path, *, artifact_ids: list[str] | None = None) -> dict[str, object]:
        """Export selected artifact bytes and metadata without secret references."""
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        rows = self.storage.connect().execute(
            "SELECT artifact_id, sha256, byte_size, media_type, path FROM artifacts ORDER BY artifact_id"
        ).fetchall()
        selected = set(artifact_ids) if artifact_ids is not None else None
        exported = []
        for row in rows:
            if selected is not None and row["artifact_id"] not in selected:
                continue
            source = Path(row["path"])
            if not source.is_file() or not self._valid_digest(source, row["sha256"]):
                raise ArtifactCommitError("artifact integrity check failed")
            target = destination / row["artifact_id"].replace(":", "_")
            target.write_bytes(source.read_bytes())
            exported.append({"artifact_id": row["artifact_id"], "sha256": row["sha256"], "byte_size": row["byte_size"], "media_type": row["media_type"]})
        manifest = {
            "format": "vesper-safe-export-v1",
            "export_id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database": "local-sqlite",
            "artifacts": exported,
        }
        temporary_manifest = destination / ".manifest.json.tmp"
        temporary_manifest.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        with temporary_manifest.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary_manifest, destination / "manifest.json")
        self._fsync_directory(destination)
        return manifest

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
