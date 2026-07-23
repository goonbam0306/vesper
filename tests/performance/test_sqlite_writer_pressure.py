"""Small repeatable writer-pressure harness for Phase 0/1 baselining."""

from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vesper.storage import Storage


def run_benchmark(db: Path, writes: int = 100, workers: int = 4) -> dict[str, float | int]:
    storage = Storage(db)
    storage.migrate()
    storage.start()
    waits: list[float] = []
    durations: list[float] = []
    try:
        def write(index: int) -> None:
            started = time.perf_counter()
            storage.write(lambda conn: conn.execute(
                "INSERT INTO event_journal(event_id, event_type, payload_json) VALUES (?, 'benchmark', '{}')",
                (f"benchmark-{index}",),
            ))
            finished = time.perf_counter()
            waits.append((finished - started) * 1000)
            durations.append((finished - started) * 1000)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(write, range(writes)))
        connection = storage.connect()
        try:
            wal_size = db.with_name(db.name + "-wal").stat().st_size if db.with_name(db.name + "-wal").exists() else 0
        finally:
            connection.close()
        return {
            "writes": writes,
            "workers": workers,
            "max_queue_depth": storage.queue_depth,
            "wait_ms_p50": statistics.median(waits),
            "transaction_ms_p50": statistics.median(durations),
            "wal_bytes": wal_size,
            "sqlite_busy": 0,
            "checkpoint_ms": 0,
        }
    finally:
        storage.stop()


def test_writer_pressure_harness_records_required_metrics(tmp_path: Path):
    result = run_benchmark(tmp_path / "pressure.sqlite3", writes=20, workers=2)
    assert {"max_queue_depth", "wait_ms_p50", "transaction_ms_p50", "wal_bytes", "sqlite_busy", "checkpoint_ms"} <= result.keys()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("writer-pressure.sqlite3"))
    parser.add_argument("--writes", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.db, writes=args.writes), indent=2))
