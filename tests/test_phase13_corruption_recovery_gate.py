import sqlite3

import pytest

from vesper.backup import backup_database, restore_database
from vesper.storage import Storage


def _database(path):
    storage = Storage(path)
    storage.migrate()
    storage.start()
    storage.write(lambda c: c.execute("CREATE TABLE IF NOT EXISTS integrity_probe (value TEXT)"))
    storage.write(lambda c: c.execute("INSERT INTO integrity_probe(value) VALUES ('stable')"))
    storage.stop()


def test_backup_detects_corruption_and_restore_uses_verified_copy(tmp_path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    _database(source)

    receipt = backup_database(source, backup)
    assert receipt["sha256"]
    assert receipt["schema_version"] > 0

    with sqlite3.connect(backup) as conn:
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute("UPDATE sqlite_master SET sql=NULL WHERE type='table' AND name='integrity_probe'")
        conn.commit()

    with pytest.raises(ValueError, match="corrupt"):
        restore_database(backup, restored, expected_schema_version=receipt["schema_version"])
    assert not restored.exists()


def test_restore_rejects_missing_or_invalid_database(tmp_path):
    invalid = tmp_path / "invalid.db"
    invalid.write_bytes(b"not sqlite")
    with pytest.raises(ValueError, match="corrupt"):
        restore_database(invalid, tmp_path / "restored.db", expected_schema_version=1)
