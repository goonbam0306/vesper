"""Reproducible interactive/background SQLite writer-pressure benchmark."""
from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vesper.storage import Storage


def run_benchmark(db: Path, writes: int = 100, workers: int = 4, background_workers: int | None = None) -> dict:
    storage = Storage(db)
    storage.migrate(); storage.start()
    waits: list[float] = []
    durations: list[float] = []
    background_workers = background_workers if background_workers is not None else workers
    try:
        def write(index: int, write_class: str) -> None:
            started = time.perf_counter()
            storage.write(lambda conn: conn.execute(
                "INSERT INTO event_journal(event_id, event_type, payload_json) VALUES (?, 'benchmark', '{}')",
                (f"benchmark-{write_class}-{index}",),
            ), write_class=write_class)
            finished = time.perf_counter()
            waits.append((finished - started) * 1000)
            durations.append((finished - started) * 1000)

        with ThreadPoolExecutor(max_workers=workers + background_workers) as pool:
            futures = [pool.submit(write, i, "interactive") for i in range(writes)]
            futures += [pool.submit(write, i, "background") for i in range(writes * max(1, background_workers))]
            for future in futures:
                future.result()
        metrics = storage.metrics
        wal = db.with_name(db.name + "-wal")
        grouped = {}
        for kind in ("interactive", "background"):
            rows = [m for m in metrics if m["class"] == kind]
            grouped[kind] = {
                "count": len(rows),
                "wait_ms_p50": statistics.median([float(m["wait_ms"]) for m in rows] or [0.0]),
                "transaction_ms_p50": statistics.median([float(m["transaction_ms"]) for m in rows] or [0.0]),
            }
        checkpoint = storage.checkpoint("PASSIVE")
        return {
            "writes": writes,
            "workers": workers,
            "background_workers": background_workers,
            "max_queue_depth": max([int(m["queue_depth"]) for m in metrics] or [0]),
            "wait_ms_p50": statistics.median(waits),
            "transaction_ms_p50": statistics.median(durations),
            "wal_bytes": wal.stat().st_size if wal.exists() else 0,
            "sqlite_busy": sum(int(m["sqlite_busy"]) for m in metrics),
            "checkpoint_ms": float(checkpoint["duration_ms"]),
            "checkpoint_mode": checkpoint["mode"],
            "checkpoint_success": checkpoint["success"],
            "checkpoint_result": checkpoint["result"],
            "by_class": grouped,
        }
    finally:
        storage.stop()


def test_writer_pressure_harness_records_required_metrics(tmp_path: Path):
    result = run_benchmark(tmp_path / "pressure.sqlite3", writes=20, workers=2, background_workers=2)
    assert {"max_queue_depth", "wait_ms_p50", "transaction_ms_p50", "wal_bytes", "sqlite_busy", "checkpoint_ms", "checkpoint_mode", "checkpoint_success", "checkpoint_result", "by_class"} <= result.keys()
    assert result["checkpoint_ms"] > 0.0
    assert result["checkpoint_mode"] == "PASSIVE"
    assert result["checkpoint_success"] is True
    assert result["by_class"]["interactive"]["count"] == 20
    assert result["by_class"]["background"]["count"] == 40


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("writer-pressure.sqlite3"))
    parser.add_argument("--writes", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--background-workers", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.db, args.writes, args.workers, args.background_workers), indent=2))
