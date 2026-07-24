from pathlib import Path

from vesper.storage import MigrationError, Storage


def test_migration_creates_recoverable_snapshot_for_existing_database(tmp_path: Path):
    db = tmp_path / "vesper.sqlite3"
    db.write_bytes(b"not-a-valid-sqlite-database")
    storage = Storage(db)
    try:
        storage.migrate()
    except Exception:
        pass
    snapshots = list(tmp_path.glob("vesper.sqlite3.pre-migration"))
    assert snapshots, "migration failure must retain a recoverable snapshot path"


def test_normal_migration_is_restartable(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate()
    storage.migrate()
    connection = storage.connect()
    try:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] >= 1
    finally:
        connection.close()
