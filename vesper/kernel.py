"""Phase 1 kernel: process identity, lifecycle, events, and command idempotency."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .storage import Storage


class ProcessStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = {ProcessStatus.COMPLETED, ProcessStatus.FAILED, ProcessStatus.CANCELLED}
ALLOWED = {
    ProcessStatus.CREATED: {ProcessStatus.RUNNING, ProcessStatus.CANCELLED},
    ProcessStatus.RUNNING: {ProcessStatus.WAITING, ProcessStatus.PAUSED, *TERMINAL},
    ProcessStatus.WAITING: {ProcessStatus.RUNNING, ProcessStatus.PAUSED, *TERMINAL},
    ProcessStatus.PAUSED: {ProcessStatus.RUNNING, *TERMINAL},
}


class KernelError(RuntimeError):
    code = "KERNEL_ERROR"


class InvalidTransition(KernelError):
    code = "INVALID_PROCESS_TRANSITION"


class RevisionConflict(KernelError):
    code = "REVISION_CONFLICT"


class IdempotencyConflict(KernelError):
    code = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True)
class Process:
    process_id: str
    status: str
    origin: str
    entry_event_id: str | None
    created_at: str
    updated_at: str
    revision: int
    volatile: bool
    parent_process_id: str | None = None


class Kernel:
    def __init__(self, storage: Storage):
        self.storage = storage

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _process(row: sqlite3.Row) -> Process:
        return Process(
            process_id=row["process_id"], status=row["status"], origin=row["origin"],
            entry_event_id=row["entry_event_id"], created_at=row["created_at"],
            updated_at=row["updated_at"], revision=row["revision"],
            volatile=bool(row["volatile"]), parent_process_id=row["parent_process_id"],
        )

    def _event(self, conn: sqlite3.Connection, process_id: str | None, kind: str, payload: dict[str, Any]) -> str:
        event_id = str(uuid.uuid4())
        sequence = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM event_journal").fetchone()[0]
        conn.execute(
            "INSERT INTO event_journal(event_id,event_type,process_id,sequence,payload_json) VALUES(?,?,?,?,?)",
            (event_id, kind, process_id, sequence, json.dumps(payload, sort_keys=True)),
        )
        return event_id

    def submit(self, origin: str, *, volatile: bool = False, client_request_id: str | None = None) -> Process:
        def op(conn: sqlite3.Connection) -> Process:
            command = json.dumps({"origin": origin, "volatile": volatile}, sort_keys=True)
            if client_request_id:
                old = conn.execute("SELECT command_json,result_json FROM command_requests WHERE client_request_id=?", (client_request_id,)).fetchone()
                if old:
                    if old["command_json"] != command:
                        raise IdempotencyConflict(client_request_id)
                    return self._process(conn.execute("SELECT * FROM processes WHERE process_id=?", (json.loads(old["result_json"])["process_id"],)).fetchone())
            pid, now = str(uuid.uuid4()), self._now()
            event = self._event(conn, pid, "PROCESS_CREATED", {"origin": origin, "volatile": volatile})
            conn.execute("INSERT INTO processes(process_id,status,origin,entry_event_id,created_at,updated_at,volatile) VALUES(?,?,?,?,?,?,?)", (pid, ProcessStatus.CREATED, origin, event, now, now, int(volatile)))
            result = {"process_id": pid}
            if client_request_id:
                conn.execute("INSERT INTO command_requests(client_request_id,command_json,result_json) VALUES(?,?,?)", (client_request_id, command, json.dumps(result)))
            return self._process(conn.execute("SELECT * FROM processes WHERE process_id=?", (pid,)).fetchone())
        return self.storage.write(op)

    def get(self, process_id: str) -> Process | None:
        return self.storage.write(lambda c: (lambda r: self._process(r) if r else None)(c.execute("SELECT * FROM processes WHERE process_id=?", (process_id,)).fetchone()))

    def transition(self, process_id: str, target: ProcessStatus, *, expected_revision: int | None = None) -> Process:
        def op(conn: sqlite3.Connection) -> Process:
            row = conn.execute("SELECT * FROM processes WHERE process_id=?", (process_id,)).fetchone()
            if not row:
                raise KernelError("PROCESS_NOT_FOUND")
            current = ProcessStatus(row["status"])
            if expected_revision is not None and row["revision"] != expected_revision:
                raise RevisionConflict(process_id)
            if target not in ALLOWED.get(current, set()):
                raise InvalidTransition(f"{current}->{target}")
            now = self._now()
            self._event(conn, process_id, f"PROCESS_{target}", {"from": current, "to": target})
            conn.execute("UPDATE processes SET status=?,revision=revision+1,updated_at=? WHERE process_id=?", (target, now, process_id))
            return self._process(conn.execute("SELECT * FROM processes WHERE process_id=?", (process_id,)).fetchone())
        return self.storage.write(op)

    def result(self, process_id: str, outputs: dict[str, Any], effects: dict[str, Any] | None = None) -> Process:
        effects = effects or {}
        def op(conn: sqlite3.Connection) -> Process:
            row = conn.execute("SELECT * FROM processes WHERE process_id=?", (process_id,)).fetchone()
            if not row or ProcessStatus(row["status"]) not in TERMINAL:
                raise KernelError("PROCESS_MUST_BE_TERMINAL")
            conn.execute("INSERT OR REPLACE INTO process_results(process_id,outputs_json,effects_json) VALUES(?,?,?)", (process_id, json.dumps(outputs), json.dumps(effects)))
            return self._process(row)
        return self.storage.write(op)

    def snapshot(self) -> dict[str, Any]:
        def read(conn: sqlite3.Connection) -> dict[str, Any]:
            rows = conn.execute("SELECT * FROM processes ORDER BY created_at").fetchall()
            cursor = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM event_journal").fetchone()[0]
            return {"processes": [asdict(self._process(r)) for r in rows], "cursor": cursor}
        return self.storage.write(read)

    def events_after(self, cursor: int) -> list[dict[str, Any]]:
        return self.storage.write(lambda c: [dict(r) for r in c.execute("SELECT * FROM event_journal WHERE sequence>? ORDER BY sequence", (cursor,)).fetchall()])

    def promote(self, process_id: str) -> Process:
        def op(conn: sqlite3.Connection) -> Process:
            row = conn.execute("SELECT * FROM processes WHERE process_id=?", (process_id,)).fetchone()
            if not row:
                raise KernelError("PROCESS_NOT_FOUND")
            if not row["volatile"]:
                return self._process(row)
            self._event(conn, process_id, "PROCESS_PROMOTED", {})
            conn.execute("UPDATE processes SET volatile=0,revision=revision+1,updated_at=? WHERE process_id=?", (self._now(), process_id))
            return self._process(conn.execute("SELECT * FROM processes WHERE process_id=?", (process_id,)).fetchone())
        return self.storage.write(op)
