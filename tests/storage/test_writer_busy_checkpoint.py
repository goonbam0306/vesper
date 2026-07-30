from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from vesper.storage import Storage, StorageBusyError


def test_checkpoint_records_actual_duration_and_result(tmp_path: Path):
    storage = Storage(tmp_path / "checkpoint.sqlite3")
    storage.migrate(); storage.start()
    try:
        storage.write(lambda conn: conn.execute(
            "INSERT INTO event_journal(event_id, event_type, payload_json) VALUES ('checkpoint-event', 'test', '{}')"
        ))
        result = storage.checkpoint("PASSIVE")
        assert result["mode"] == "PASSIVE"
        assert result["success"] is True
        assert result["duration_ms"] > 0.0
        assert result["result"] == 0
    finally:
        storage.stop()


def test_busy_lock_is_retried_then_commit_succeeds(tmp_path: Path):
    db = tmp_path / "busy-success.sqlite3"
    storage = Storage(db, busy_retry_limit=4, busy_backoff_ms=5)
    storage.migrate(); storage.start()
    lock = sqlite3.connect(db, timeout=0, check_same_thread=False)
    lock.execute("PRAGMA foreign_keys = ON")
    lock.execute("PRAGMA journal_mode = WAL")
    lock.execute("BEGIN EXCLUSIVE")
    finished = threading.Event()
    try:
        def release() -> None:
            time.sleep(0.03)
            lock.commit()
            lock.close()
            finished.set()
        threading.Thread(target=release, daemon=True).start()
        storage.write(lambda conn: conn.execute(
            "INSERT INTO event_journal(event_id, event_type, payload_json) VALUES ('busy-success', 'test', '{}')"
        ))
        assert finished.wait(1)
        metric = storage.metrics[-1]
        assert metric["sqlite_busy"] >= 1
        assert metric["busy_retries"] >= 1
        assert metric["busy_backoff_ms"] > 0
        assert storage.connect().execute("SELECT COUNT(*) FROM event_journal WHERE event_id = 'busy-success'").fetchone()[0] == 1
    finally:
        if not finished.is_set():
            lock.rollback(); lock.close()
        storage.stop()


def test_busy_lock_terminates_at_bounded_retry_limit_without_commit(tmp_path: Path):
    db = tmp_path / "busy-fail.sqlite3"
    storage = Storage(db, busy_retry_limit=2, busy_backoff_ms=2)
    storage.migrate(); storage.start()
    storage.write(lambda conn: conn.execute("SELECT 1"))
    lock = sqlite3.connect(db, timeout=0, check_same_thread=False)
    lock.execute("PRAGMA foreign_keys = ON")
    lock.execute("PRAGMA journal_mode = WAL")
    lock.execute("BEGIN EXCLUSIVE")
    started = time.perf_counter()
    try:
        with pytest.raises(StorageBusyError) as error:
            storage.write(lambda conn: conn.execute(
                "INSERT INTO event_journal(event_id, event_type, payload_json) VALUES ('busy-fail', 'test', '{}')"
            ))
        assert error.value.retries == 2
        assert time.perf_counter() - started < 1.0
        metric = storage.metrics[-1]
        assert metric["sqlite_busy"] == 1
        assert metric["busy_retries"] == 2
        assert storage.connect().execute("SELECT COUNT(*) FROM event_journal WHERE event_id = 'busy-fail'").fetchone()[0] == 0
    finally:
        lock.rollback(); lock.close(); storage.stop()


def test_checkpoint_does_not_starve_queued_interactive_write(tmp_path: Path):
    storage = Storage(tmp_path / "checkpoint-latency.sqlite3")
    storage.migrate(); storage.start()
    try:
        for index in range(100):
            storage.write(lambda conn, i=index: conn.execute(
                "INSERT INTO event_journal(event_id, event_type, payload_json) VALUES (?, 'test', '{}')", (f"seed-{i}",)
            ), write_class="background")
        checkpoint = storage.checkpoint("PASSIVE")
        storage.write(lambda conn: conn.execute(
            "INSERT INTO event_journal(event_id, event_type, payload_json) VALUES ('after-checkpoint', 'test', '{}')"
        ), write_class="interactive")
        interactive = [m for m in storage.metrics if m["class"] == "interactive"][-1]
        assert checkpoint["duration_ms"] > 0.0
        assert interactive["wait_ms"] < 1000.0
    finally:
        storage.stop()


def test_real_sqlite_contention_path_is_exercised(tmp_path: Path):
    db = tmp_path / "contention.sqlite3"
    storage = Storage(db, busy_retry_limit=1, busy_backoff_ms=1)
    storage.migrate(); storage.start()
    # Ensure the writer has opened its WAL connection before another connection takes the lock.
    storage.write(lambda conn: conn.execute("SELECT 1"))
    lock = sqlite3.connect(db, timeout=0, check_same_thread=False)
    lock.execute("PRAGMA journal_mode = WAL")
    lock.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(StorageBusyError):
            storage.write(lambda conn: conn.execute(
                "INSERT INTO event_journal(event_id, event_type, payload_json) VALUES ('contention', 'test', '{}')"
            ))
        assert storage.metrics[-1]["sqlite_busy"] == 1
    finally:
        lock.rollback(); lock.close(); storage.stop()
