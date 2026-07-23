from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vesper.storage import Storage


def test_concurrent_writes_are_serialized(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate()
    storage.start()
    try:
        def insert(index: int):
            return storage.write(
                lambda conn: conn.execute(
                    "INSERT INTO event_journal(event_id, event_type, payload_json) VALUES (?, 'load', '{}')",
                    (f"event-{index}",),
                ).rowcount
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(insert, range(40))) == 40
        count = storage.write(lambda conn: conn.execute("SELECT COUNT(*) FROM event_journal").fetchone()[0])
        assert count == 40
    finally:
        storage.stop()
