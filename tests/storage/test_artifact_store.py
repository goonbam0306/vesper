from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from vesper.artifacts import ArtifactStore, ArtifactCommitError
from vesper.storage import Storage


def test_artifact_publication_is_content_addressed_and_durable(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate()
    storage.start()
    try:
        store = ArtifactStore(tmp_path, storage)
        artifact = store.publish(b"hello", media_type="text/plain")
        assert artifact.artifact_id == "sha256:" + __import__("hashlib").sha256(b"hello").hexdigest()
        assert artifact.path.is_file()
        assert artifact.path.read_bytes() == b"hello"
        row = storage.connect().execute(
            "SELECT artifact_id, byte_size, sha256 FROM artifacts WHERE artifact_id = ?",
            (artifact.artifact_id,),
        ).fetchone()
        assert tuple(row) == (artifact.artifact_id, 5, artifact.artifact_id.removeprefix("sha256:"))
    finally:
        storage.stop()


def test_duplicate_content_reuses_canonical_artifact(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    try:
        store = ArtifactStore(tmp_path, storage)
        first = store.publish(b"same")
        second = store.publish(b"same")
        assert first.artifact_id == second.artifact_id
        conn = storage.connect()
        assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1
        conn.close()
    finally:
        storage.stop()


def test_db_reference_is_never_committed_when_publication_fails(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    try:
        store = ArtifactStore(tmp_path, storage)
        with pytest.raises(ArtifactCommitError):
            store.publish(b"bad", fault="before_db_commit")
        conn = storage.connect()
        assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
        conn.close()
    finally:
        storage.stop()


def test_orphan_bytes_are_recoverable_without_dangling_reference(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    try:
        store = ArtifactStore(tmp_path, storage)
        with pytest.raises(ArtifactCommitError):
            store.publish(b"orphan", fault="after_rename_before_db")
        orphan = next(store.content_root.glob("??/*"))
        assert orphan.exists()
        assert store.reconcile() == 1
        conn = storage.connect()
        assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1
        conn.close()
    finally:
        storage.stop()


def test_runtime_directories_are_created(tmp_path: Path):
    store = ArtifactStore(tmp_path, Storage(tmp_path / "vesper.sqlite3"))
    assert store.root.is_dir()
    assert store.staging.is_dir()
    assert store.content_root.is_dir()


def test_artifact_store_requires_kernel_storage_writer(tmp_path: Path):
    with pytest.raises(TypeError):
        ArtifactStore(tmp_path, sqlite3.connect(tmp_path / "bad.sqlite3"))


def test_orphan_cleanup_removes_unreferenced_bytes(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    try:
        store = ArtifactStore(tmp_path, storage)
        with pytest.raises(ArtifactCommitError):
            store.publish(b"cleanup", fault="after_rename_before_db")
        artifact = next(store.content_root.glob("??/*"))
        assert store.cleanup_orphans() == 1
        assert not artifact.exists()
    finally:
        storage.stop()


def test_no_staging_files_remain_after_success(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    try:
        store = ArtifactStore(tmp_path, storage)
        store.publish(b"clean")
        assert list(store.staging.iterdir()) == []
    finally:
        storage.stop()
