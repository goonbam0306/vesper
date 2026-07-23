"""SQLite canonical substrate with a single serialized writer path."""

from __future__ import annotations

import queue
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


class MigrationError(RuntimeError):
    """Raised when a migration cannot be applied."""


class Storage:
    def __init__(self, path: Path, migrations_dir: Path | None = None) -> None:
        self.path = path
        self.migrations_dir = migrations_dir or Path(__file__).resolve().parent.parent / "migrations"
        self._queue: queue.Queue[tuple[Callable[[sqlite3.Connection], Any], queue.Queue[Any]] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = False
        self._start_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot: Path | None = None
        if self.path.exists() and self.path.stat().st_size > 0:
            snapshot = self.path.with_suffix(self.path.suffix + ".pre-migration")
            snapshot.write_bytes(self.path.read_bytes())
        connection = self.connect()
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            current = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
            migrations = sorted(self.migrations_dir.glob("*.sql"))
            for migration in migrations:
                version = int(migration.stem.split("_", 1)[0])
                if version <= current:
                    continue
                if snapshot is None and self.path.exists():
                    snapshot = self.path.with_suffix(self.path.suffix + ".pre-migration")
                    connection.commit()
                    connection.close()
                    snapshot.write_bytes(self.path.read_bytes())
                    connection = self.connect()
                try:
                    connection.executescript(migration.read_text(encoding="utf-8"))
                    connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
                    connection.commit()
                except Exception as exc:
                    connection.rollback()
                    raise MigrationError(f"migration {migration.name} failed; snapshot={snapshot}") from exc
        finally:
            connection.close()

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            self._thread = threading.Thread(target=self._writer_loop, name="vesper-storage-writer", daemon=True)
            self._thread.start()
            self._started = True

    def stop(self) -> None:
        with self._start_lock:
            if not self._started:
                return
            self._queue.put(None)
            assert self._thread is not None
            self._thread.join(timeout=5)
            self._thread = None
            self._started = False

    def write(self, operation: Callable[[sqlite3.Connection], T], timeout: float = 10.0) -> T:
        if not self._started:
            raise RuntimeError("storage writer is not started")
        result: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._queue.put((operation, result))
        value = result.get(timeout=timeout)
        if isinstance(value, BaseException):
            raise value
        return value

    def _writer_loop(self) -> None:
        connection = self.connect()
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                operation, result = item
                try:
                    value = operation(connection)
                    connection.commit()
                    result.put(value)
                except BaseException as exc:
                    connection.rollback()
                    result.put(exc)
        finally:
            connection.close()

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()
