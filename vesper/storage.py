"""SQLite canonical substrate with a single serialized writer path."""
from __future__ import annotations

import hashlib
import queue
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")
_MIGRATION_NAME = re.compile(r"^(?P<version>\d+)_(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)\.sql$")


class MigrationError(RuntimeError):
    """Raised when a migration cannot be applied safely."""


class MigrationIdentityError(MigrationError):
    """Raised when migration versions, names, or recorded checksums conflict."""


class StorageBusyError(RuntimeError):
    """A write exceeded the bounded SQLite BUSY/locked retry policy."""

    def __init__(self, retries: int, backoff_ms: float, cause: BaseException) -> None:
        super().__init__(f"SQLite remained busy after {retries} retries ({backoff_ms:.2f}ms backoff)")
        self.retries = retries
        self.backoff_ms = backoff_ms
        self.__cause__ = cause


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str


class Storage:
    def __init__(
        self,
        path: Path,
        migrations_dir: Path | None = None,
        *,
        busy_retry_limit: int = 3,
        busy_backoff_ms: float = 10.0,
    ) -> None:
        self.path = path
        self.migrations_dir = migrations_dir or Path(__file__).resolve().parent.parent / "migrations"
        self.busy_retry_limit = busy_retry_limit
        self.busy_backoff_ms = busy_backoff_ms
        self._queue: queue.Queue[tuple[Callable[[sqlite3.Connection], Any], queue.Queue[Any], str, float] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = False
        self._start_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._metrics: list[dict[str, float | int | str | bool]] = []

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=0.0, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 0")
        return connection

    def migration_inventory(self) -> tuple[Migration, ...]:
        """Parse and validate revision identities; ordering authority is numeric version, never filename order."""
        found: list[Migration] = []
        versions: dict[int, str] = {}
        for path in self.migrations_dir.glob("*.sql"):
            match = _MIGRATION_NAME.fullmatch(path.name)
            if not match:
                raise MigrationIdentityError(f"invalid migration filename: {path.name}")
            version = int(match.group("version"))
            if version in versions:
                raise MigrationIdentityError(f"duplicate migration version {version}: {versions[version]} and {path.name}")
            content = path.read_bytes()
            found.append(Migration(version, match.group("name"), path, hashlib.sha256(content).hexdigest()))
            versions[version] = path.name
        return tuple(sorted(found, key=lambda migration: migration.version))

    @staticmethod
    def _ensure_migration_metadata(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(schema_migrations)")}
        if "name" not in columns:
            connection.execute("ALTER TABLE schema_migrations ADD COLUMN name TEXT")
        if "checksum" not in columns:
            connection.execute("ALTER TABLE schema_migrations ADD COLUMN checksum TEXT")

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        migrations = self.migration_inventory()  # Validate before touching an existing DB.
        snapshot: Path | None = None
        if self.path.exists() and self.path.stat().st_size > 0:
            snapshot = self.path.with_suffix(self.path.suffix + ".pre-migration")
            snapshot.write_bytes(self.path.read_bytes())
        connection = self.connect()
        try:
            self._ensure_migration_metadata(connection)
            applied_rows = {row["version"]: row for row in connection.execute("SELECT version,name,checksum FROM schema_migrations")}
            inventory_versions = {migration.version for migration in migrations}
            unknown = set(applied_rows) - inventory_versions
            if unknown:
                raise MigrationIdentityError(f"database records migrations absent from repository: {sorted(unknown)}")
            for migration in migrations:
                applied = applied_rows.get(migration.version)
                if not applied:
                    continue
                recorded_name, recorded_checksum = applied["name"], applied["checksum"]
                # Legacy records lack metadata; backfill without treating historical content as changed.
                if recorded_name is None and recorded_checksum is None:
                    connection.execute("UPDATE schema_migrations SET name=?, checksum=? WHERE version=?", (migration.name, migration.checksum, migration.version))
                elif recorded_name != migration.name or recorded_checksum != migration.checksum:
                    raise MigrationIdentityError(f"applied migration identity changed at version {migration.version}: {migration.path.name}")
            connection.commit()
            for migration in migrations:
                if migration.version in applied_rows:
                    continue
                if snapshot is None and self.path.exists():
                    snapshot = self.path.with_suffix(self.path.suffix + ".pre-migration")
                    connection.commit(); connection.close()
                    snapshot.write_bytes(self.path.read_bytes())
                    connection = self.connect()
                try:
                    # executescript commits implicitly; run a transaction-wrapped script so schema and identity record are atomic.
                    script = migration.path.read_text(encoding="utf-8")
                    connection.executescript("BEGIN IMMEDIATE;\n" + script + "\nINSERT INTO schema_migrations(version,name,checksum) VALUES (" + str(migration.version) + "," + repr(migration.name) + "," + repr(migration.checksum) + ");\nCOMMIT;")
                except Exception as exc:
                    connection.rollback()
                    raise MigrationError(f"migration {migration.path.name} failed; snapshot={snapshot}") from exc
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

    def write(self, operation: Callable[[sqlite3.Connection], T], timeout: float = 10.0, write_class: str = "interactive") -> T:
        if not self._started:
            raise RuntimeError("storage writer is not started")
        result: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._queue.put((operation, result, write_class, time.perf_counter()))
        value = result.get(timeout=timeout)
        if isinstance(value, BaseException):
            raise value
        return value

    def checkpoint(self, mode: str = "PASSIVE", timeout: float = 10.0) -> dict[str, float | int | str | bool]:
        normalized = mode.upper()
        if normalized not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise ValueError(f"unsupported checkpoint mode: {mode}")
        def operation(conn: sqlite3.Connection) -> dict[str, float | int | str | bool]:
            started = time.perf_counter()
            try:
                result, log_frames, checkpointed_frames = conn.execute(f"PRAGMA wal_checkpoint({normalized})").fetchone()
                return {"mode": normalized, "result": int(result), "log_frames": int(log_frames), "checkpointed_frames": int(checkpointed_frames), "success": int(result) == 0, "duration_ms": (time.perf_counter() - started) * 1000}
            except sqlite3.Error as exc:
                return {"mode": normalized, "result": -1, "log_frames": 0, "checkpointed_frames": 0, "success": False, "duration_ms": (time.perf_counter() - started) * 1000, "error": str(exc)}
        result = self.write(operation, timeout=timeout, write_class="checkpoint")
        with self._metrics_lock:
            if self._metrics:
                self._metrics[-1]["checkpoint_ms"] = float(result["duration_ms"])
                self._metrics[-1]["checkpoint_mode"] = normalized
                self._metrics[-1]["checkpoint_success"] = bool(result["success"])
        return result

    def _writer_loop(self) -> None:
        connection = self.connect()
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                operation, result, write_class, enqueued = item
                started = time.perf_counter(); retries = 0; backoff_total_ms = 0.0
                while True:
                    try:
                        value = operation(connection); connection.commit()
                        self._record_metric(write_class, enqueued, started, time.perf_counter(), retries, backoff_total_ms, int(retries > 0)); result.put(value); break
                    except sqlite3.OperationalError as exc:
                        connection.rollback()
                        if not self._is_busy(exc):
                            self._record_metric(write_class, enqueued, started, time.perf_counter(), retries, backoff_total_ms, 0); result.put(exc); break
                        if retries >= self.busy_retry_limit:
                            failure = StorageBusyError(retries, backoff_total_ms, exc)
                            self._record_metric(write_class, enqueued, started, time.perf_counter(), retries, backoff_total_ms, 1); result.put(failure); break
                        delay_ms = self.busy_backoff_ms * (2 ** retries); retries += 1; backoff_total_ms += delay_ms; time.sleep(delay_ms / 1000)
                    except BaseException as exc:
                        connection.rollback(); self._record_metric(write_class, enqueued, started, time.perf_counter(), retries, backoff_total_ms, 0); result.put(exc); break
        finally:
            connection.close()

    def _record_metric(self, write_class: str, enqueued: float, started: float, finished: float, retries: int, backoff_total_ms: float, busy: int) -> None:
        wal = self.path.with_name(self.path.name + "-wal")
        with self._metrics_lock:
            self._metrics.append({"class": write_class, "queue_depth": self._queue.qsize(), "wait_ms": (started - enqueued) * 1000, "transaction_ms": (finished - started) * 1000, "wal_bytes": wal.stat().st_size if wal.exists() else 0, "checkpoint_ms": 0.0, "sqlite_busy": busy, "busy_retries": retries, "busy_backoff_ms": backoff_total_ms})

    @staticmethod
    def _is_busy(error: sqlite3.OperationalError) -> bool:
        message = str(error).lower()
        return "locked" in message or "busy" in message

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def metrics(self) -> list[dict[str, float | int | str | bool]]:
        with self._metrics_lock:
            return list(self._metrics)
