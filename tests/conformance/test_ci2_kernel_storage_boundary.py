from pathlib import Path

from vesper.storage import Storage


def test_storage_has_one_serialized_writer_boundary(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate()
    storage.start()
    try:
        storage.write(lambda conn: conn.execute("INSERT INTO event_journal(event_id, event_type, payload_json) VALUES ('e1', 'test', '{}')"))
        row = storage.write(lambda conn: conn.execute("SELECT COUNT(*) AS count FROM event_journal").fetchone())
        assert row["count"] == 1
    finally:
        storage.stop()


def test_storage_uses_wal_and_foreign_keys(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    connection = storage.connect()
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()
