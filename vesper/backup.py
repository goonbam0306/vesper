"""Local backup/restore with schema-version verification and no secret serialization."""
import hashlib
import shutil
import sqlite3
from pathlib import Path


def _schema_version(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def backup_database(source: Path, target: Path) -> dict[str, int | str]:
    if source.resolve() == target.resolve():
        raise ValueError("backup target must differ from source")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {"schema_version": _schema_version(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def restore_database(source: Path, target: Path, *, expected_schema_version: int) -> None:
    try:
        with sqlite3.connect(source) as conn:
            conn.execute("PRAGMA quick_check")
            quick_check = conn.execute("PRAGMA integrity_check").fetchone()
            if not quick_check or quick_check[0] != "ok":
                raise ValueError("backup is corrupt")
            schema_version = _schema_version(source)
    except (sqlite3.DatabaseError, OSError) as exc:
        raise ValueError("backup is corrupt") from exc
    if schema_version != expected_schema_version:
        raise ValueError("backup schema version mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)