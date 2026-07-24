"""Phase 1 execution kernel: process identity, lifecycle, scheduling, and durable events."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
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


class WaitReason(StrEnum):
    APPROVAL = "approval"
    USER_INPUT = "user_input"
    EXTERNAL_IO = "external_io"
    TIMER = "timer"
    CHILD = "child"
    RESOURCE = "resource"


class PriorityClass(StrEnum):
    INTERACTIVE = "INTERACTIVE"
    NORMAL = "NORMAL"
    BACKGROUND = "BACKGROUND"


TERMINAL = {ProcessStatus.COMPLETED, ProcessStatus.FAILED, ProcessStatus.CANCELLED}
ALLOWED = {
    ProcessStatus.CREATED: {ProcessStatus.RUNNING, ProcessStatus.WAITING, ProcessStatus.CANCELLED},
    ProcessStatus.RUNNING: {ProcessStatus.WAITING, ProcessStatus.PAUSED, *TERMINAL},
    ProcessStatus.WAITING: {ProcessStatus.RUNNING, ProcessStatus.PAUSED, *TERMINAL},
    ProcessStatus.PAUSED: {ProcessStatus.RUNNING, *TERMINAL},
}


class KernelError(RuntimeError):
    code = "KERNEL_ERROR"
    retryable = False


class InvalidTransition(KernelError):
    code = "INVALID_PROCESS_TRANSITION"


class RevisionConflict(KernelError):
    code = "REVISION_CONFLICT"
    retryable = True


class IdempotencyConflict(KernelError):
    code = "IDEMPOTENCY_CONFLICT"


class AuthorityViolation(KernelError):
    code = "AUTHORITY_ATTENUATION_REQUIRED"


class DependencyCycle(KernelError):
    code = "DEPENDENCY_CYCLE"


class CursorExpired(KernelError):
    code = "CURSOR_EXPIRED"


class ProcessNotFound(KernelError):
    code = "PROCESS_NOT_FOUND"


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
    authority: tuple[str, ...] = ()
    delegable_authority: tuple[str, ...] = ()
    priority: str = PriorityClass.NORMAL


@dataclass
class ScheduledItem:
    process_id: str
    priority: PriorityClass
    enqueued_at: float
    enqueued_slice: int


class ProcessScheduler:
    """Cooperative, process-level scheduler; deliberately independent from model routing."""

    def __init__(
        self,
        aging_seconds: float = 0.025,
        *,
        normal_age_slices: int = 8,
        background_age_slices: int = 6,
    ) -> None:
        # TUNABLE: bounded slice aging prevents starvation without erasing base priority.
        self.aging_seconds = aging_seconds
        self.normal_age_slices = normal_age_slices
        self.background_age_slices = background_age_slices
        self.queues: dict[PriorityClass, deque[ScheduledItem]] = {priority: deque() for priority in PriorityClass}
        self.enqueued: set[str] = set()
        self.total_slices = 0
        self.interactive_starved = False
        self.max_interactive_latency_ms = 0.0

    def enqueue(self, process_id: str, priority: PriorityClass) -> None:
        if process_id in self.enqueued:
            return
        item = ScheduledItem(process_id, priority, time.perf_counter(), self.total_slices)
        self.queues[priority].append(item)
        self.enqueued.add(process_id)

    def discard(self, process_id: str) -> None:
        self.enqueued.discard(process_id)

    def next(self) -> ScheduledItem | None:
        now = time.perf_counter()
        # Promotion is intentionally bounded: one aged lower-priority slice at a time.
        # Base priority remains dominant until its queue head crosses its tunable threshold.
        aged: list[tuple[float, PriorityClass]] = []
        for priority, threshold in (
            (PriorityClass.NORMAL, self.normal_age_slices),
            (PriorityClass.BACKGROUND, self.background_age_slices),
        ):
            if self.queues[priority]:
                waited_slices = self.total_slices - self.queues[priority][0].enqueued_slice
                if waited_slices >= threshold:
                    aged.append((self.queues[priority][0].enqueued_at, priority))
        if aged:
            _, priority = min(aged)
            item = self.queues[priority].popleft()
        else:
            item = next((self.queues[priority].popleft() for priority in (PriorityClass.INTERACTIVE, PriorityClass.NORMAL, PriorityClass.BACKGROUND) if self.queues[priority]), None)
        if item is None:
            return None
        self.enqueued.discard(item.process_id)
        if item.priority == PriorityClass.INTERACTIVE:
            self.max_interactive_latency_ms = max(self.max_interactive_latency_ms, (now - item.enqueued_at) * 1000)
        self.total_slices += 1
        return item

    def metrics(self) -> dict[str, Any]:
        return {
            "interactive_queue_depth": len(self.queues[PriorityClass.INTERACTIVE]),
            "normal_queue_depth": len(self.queues[PriorityClass.NORMAL]),
            "background_queue_depth": len(self.queues[PriorityClass.BACKGROUND]),
            "runnable_processes": len(self.enqueued),
            "waiting_processes": 0,
            "interactive_starved": self.interactive_starved,
            "interactive_scheduling_latency_ms": self.max_interactive_latency_ms,
            "slices": self.total_slices,
        }


class Kernel:
    def __init__(self, storage: Storage):
        self.storage = storage
        self._volatile: dict[str, Process] = {}
        self._volatile_waits: dict[str, tuple[WaitReason, str]] = {}
        self.scheduler = ProcessScheduler()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_authority(values: set[str] | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
        return tuple(sorted(set(values or ())))

    @staticmethod
    def _priority(value: str | PriorityClass) -> PriorityClass:
        return PriorityClass(str(value).upper())

    def _process(self, row: sqlite3.Row) -> Process:
        auth = row["authority_json"] if "authority_json" in row.keys() else "[]"
        delegated = row["delegable_authority_json"] if "delegable_authority_json" in row.keys() else "[]"
        return Process(
            process_id=row["process_id"], status=row["status"], origin=row["origin"],
            entry_event_id=row["entry_event_id"], created_at=row["created_at"],
            updated_at=row["updated_at"], revision=row["revision"], volatile=bool(row["volatile"]),
            parent_process_id=row["parent_process_id"], authority=tuple(json.loads(auth)),
            delegable_authority=tuple(json.loads(delegated)), priority=PriorityClass.NORMAL,
        )

    def _load(self, conn: sqlite3.Connection, process_id: str) -> Process | None:
        row = conn.execute(
            "SELECT p.*, a.authority_json, a.delegable_authority_json FROM processes p "
            "LEFT JOIN process_authority a USING(process_id) WHERE p.process_id=?", (process_id,)
        ).fetchone()
        return self._process(row) if row else None

    def _event(self, conn: sqlite3.Connection, process_id: str | None, kind: str, payload: dict[str, Any]) -> str:
        event_id = str(uuid.uuid4())
        sequence = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM event_journal").fetchone()[0]
        conn.execute(
            "INSERT INTO event_journal(event_id,event_type,process_id,sequence,payload_json) VALUES(?,?,?,?,?)",
            (event_id, kind, process_id, sequence, json.dumps(payload, sort_keys=True)),
        )
        return event_id

    def _record_cursor(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM event_journal").fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO watch_cursors(cursor, created_at) VALUES(?, ?)", (cursor, self._now()))

    def submit(
        self,
        origin: str,
        *,
        volatile: bool = False,
        client_request_id: str | None = None,
        authority: set[str] | list[str] | tuple[str, ...] | None = None,
        delegable_authority: set[str] | list[str] | tuple[str, ...] | None = None,
        priority: str | PriorityClass = PriorityClass.NORMAL,
    ) -> Process:
        normalized_authority = self._normalize_authority(authority)
        normalized_delegable = self._normalize_authority(delegable_authority or normalized_authority)
        if not set(normalized_delegable).issubset(normalized_authority):
            raise AuthorityViolation("delegable authority must be a subset of effective authority")
        command = json.dumps({"origin": origin, "volatile": volatile, "authority": normalized_authority, "delegable_authority": normalized_delegable, "priority": str(priority)}, sort_keys=True)
        pid, now = str(uuid.uuid4()), self._now()
        process = Process(pid, ProcessStatus.CREATED, origin, None, now, now, 0, volatile, None, normalized_authority, normalized_delegable, str(self._priority(priority)))
        if volatile:
            if client_request_id:
                existing = getattr(self, "_volatile_requests", {}).get(client_request_id) if hasattr(self, "_volatile_requests") else None
                if existing:
                    if existing[0] != command:
                        raise IdempotencyConflict(client_request_id)
                    return existing[1]
                self._volatile_requests = getattr(self, "_volatile_requests", {})
                self._volatile_requests[client_request_id] = (command, process)
            self._volatile[pid] = process
            self.scheduler.enqueue(pid, self._priority(priority))
            return process

        def op(conn: sqlite3.Connection) -> Process:
            if client_request_id:
                old = conn.execute("SELECT command_json,result_json FROM command_requests WHERE client_request_id=?", (client_request_id,)).fetchone()
                if old:
                    if old["command_json"] != command:
                        raise IdempotencyConflict(client_request_id)
                    return self._load(conn, json.loads(old["result_json"])["process_id"])
            event = self._event(conn, pid, "PROCESS_CREATED", {"origin": origin})
            conn.execute("INSERT INTO processes(process_id,status,origin,entry_event_id,created_at,updated_at,volatile) VALUES(?,?,?,?,?,?,0)", (pid, ProcessStatus.CREATED, origin, event, now, now))
            conn.execute("INSERT INTO process_authority(process_id,authority_json,delegable_authority_json) VALUES(?,?,?)", (pid, json.dumps(normalized_authority), json.dumps(normalized_delegable)))
            if client_request_id:
                conn.execute("INSERT INTO command_requests(client_request_id,command_json,result_json) VALUES(?,?,?)", (client_request_id, command, json.dumps({"process_id": pid})))
            self._record_cursor(conn)
            return self._load(conn, pid)

        result = self.storage.write(op)
        self.scheduler.enqueue(result.process_id, self._priority(priority))
        return result

    def get(self, process_id: str) -> Process | None:
        if process_id in self._volatile:
            return self._volatile[process_id]
        return self.storage.write(lambda conn: self._load(conn, process_id))

    def promote(self, process_id: str, *, boundary: str = "explicit_save", fault_after_event: bool = False) -> Process:
        if process_id not in self._volatile:
            found = self.get(process_id)
            if found is None:
                raise ProcessNotFound(process_id)
            return found
        source = self._volatile[process_id]

        def op(conn: sqlite3.Connection) -> Process:
            event = self._event(conn, process_id, "PROCESS_PROMOTED", {"boundary": boundary})
            if fault_after_event:
                raise RuntimeError("injected promotion fault")
            conn.execute("INSERT INTO processes(process_id,status,origin,entry_event_id,created_at,updated_at,revision,volatile,parent_process_id) VALUES(?,?,?,?,?,?,?,?,?)", (source.process_id, source.status, source.origin, event, source.created_at, self._now(), source.revision + 1, 0, source.parent_process_id))
            conn.execute("INSERT INTO process_authority(process_id,authority_json,delegable_authority_json) VALUES(?,?,?)", (process_id, json.dumps(source.authority), json.dumps(source.delegable_authority)))
            self._record_cursor(conn)
            return self._load(conn, process_id)

        durable = self.storage.write(op)
        self._volatile.pop(process_id, None)
        self._volatile_waits.pop(process_id, None)
        return durable

    def _dependency_outcomes(self, conn: sqlite3.Connection, process_id: str) -> list[dict[str, str]]:
        rows = conn.execute(
            "SELECT d.depends_on_process_id, p.status FROM process_dependencies d "
            "JOIN processes p ON p.process_id=d.depends_on_process_id "
            "WHERE d.process_id=? ORDER BY d.depends_on_process_id",
            (process_id,),
        ).fetchall()
        outcomes: list[dict[str, str]] = []
        for row in rows:
            status = ProcessStatus(row["status"])
            outcome = "SATISFIED" if status == ProcessStatus.COMPLETED else (
                "BLOCKED_BY_DEPENDENCY" if status in {ProcessStatus.FAILED, ProcessStatus.CANCELLED} else "PENDING"
            )
            outcomes.append({"process_id": row["depends_on_process_id"], "status": status, "outcome": outcome})
        return outcomes

    def dependency_outcomes(self, process_id: str) -> list[dict[str, str]]:
        return self.storage.write(lambda conn: self._dependency_outcomes(conn, process_id))

    def _dependencies_satisfied(self, conn: sqlite3.Connection, process_id: str) -> bool:
        return all(item["outcome"] == "SATISFIED" for item in self._dependency_outcomes(conn, process_id))

    def _failed_dependency_outcome(self, conn: sqlite3.Connection, process_id: str) -> dict[str, str] | None:
        return next((item for item in self._dependency_outcomes(conn, process_id) if item["outcome"] == "BLOCKED_BY_DEPENDENCY"), None)

    def transition(self, process_id: str, target: ProcessStatus, *, expected_revision: int | None = None, fault_after_event: bool = False) -> Process:
        volatile = self._volatile.get(process_id)
        if volatile:
            current = ProcessStatus(volatile.status)
            if target not in ALLOWED.get(current, set()):
                raise InvalidTransition(f"{current}->{target}")
            if target == ProcessStatus.RUNNING:
                self.scheduler.discard(process_id)
            changed = Process(volatile.process_id, target, volatile.origin, None, volatile.created_at, self._now(), volatile.revision + 1, True, volatile.parent_process_id, volatile.authority, volatile.delegable_authority, volatile.priority)
            self._volatile[process_id] = changed
            return changed

        def op(conn: sqlite3.Connection) -> Process:
            current = self._load(conn, process_id)
            if current is None:
                raise ProcessNotFound(process_id)
            if expected_revision is not None and current.revision != expected_revision:
                raise RevisionConflict(process_id)
            current_status = ProcessStatus(current.status)
            if target not in ALLOWED.get(current_status, set()):
                raise InvalidTransition(f"{current_status}->{target}")
            if target == ProcessStatus.RUNNING:
                blocked = self._failed_dependency_outcome(conn, process_id)
                if blocked:
                    raise InvalidTransition(
                        f"dependency blocked: {blocked['process_id']}={blocked['status']}"
                    )
                if not self._dependencies_satisfied(conn, process_id):
                    raise InvalidTransition("unmet dependency")
            self._event(conn, process_id, f"PROCESS_{target}", {"from": current_status, "to": target})
            if fault_after_event:
                raise RuntimeError("injected transition fault")
            conn.execute("UPDATE processes SET status=?,revision=revision+1,updated_at=? WHERE process_id=?", (target, self._now(), process_id))
            if target != ProcessStatus.WAITING:
                conn.execute("DELETE FROM process_waits WHERE process_id=?", (process_id,))
            self._record_cursor(conn)
            return self._load(conn, process_id)

        result = self.storage.write(op)
        if target == ProcessStatus.RUNNING:
            self.scheduler.discard(process_id)
        return result

    def wait(self, process_id: str, reason: WaitReason, *, wake_key: str) -> Process:
        process = self.get(process_id)
        if process is None:
            raise ProcessNotFound(process_id)
        if process.volatile:
            self.promote(process_id, boundary="durable_wait")
        def op(conn: sqlite3.Connection) -> Process:
            current = self._load(conn, process_id)
            if current is None or ProcessStatus(current.status) != ProcessStatus.RUNNING:
                raise InvalidTransition("wait requires RUNNING")
            self._event(conn, process_id, "PROCESS_WAITING", {"reason": reason, "wake_key": wake_key})
            conn.execute("UPDATE processes SET status=?,revision=revision+1,updated_at=? WHERE process_id=?", (ProcessStatus.WAITING, self._now(), process_id))
            conn.execute("INSERT OR REPLACE INTO process_waits(process_id,reason,wake_key,created_at) VALUES(?,?,?,?)", (process_id, reason, wake_key, self._now()))
            self._record_cursor(conn)
            return self._load(conn, process_id)
        self.scheduler.discard(process_id)
        return self.storage.write(op)

    def wake(self, wake_key: str) -> list[Process]:
        def op(conn: sqlite3.Connection) -> list[Process]:
            rows = conn.execute("SELECT process_id FROM process_waits WHERE wake_key=? ORDER BY created_at", (wake_key,)).fetchall()
            resumed: list[Process] = []
            for row in rows:
                pid = row["process_id"]
                self._event(conn, pid, "PROCESS_WOKEN", {"wake_key": wake_key})
                conn.execute("UPDATE processes SET status=?,revision=revision+1,updated_at=? WHERE process_id=? AND status=?", (ProcessStatus.RUNNING, self._now(), pid, ProcessStatus.WAITING))
                conn.execute("DELETE FROM process_waits WHERE process_id=?", (pid,))
                resumed.append(self._load(conn, pid))
            if resumed:
                self._record_cursor(conn)
            return resumed
        resumed = self.storage.write(op)
        for process in resumed:
            self.scheduler.enqueue(process.process_id, self._priority(process.priority))
        return resumed

    def spawn(self, parent_process_id: str, *, authority: set[str] | list[str] | tuple[str, ...], delegation_package: dict[str, Any] | None = None, priority: str | PriorityClass = PriorityClass.NORMAL) -> Process:
        parent = self.get(parent_process_id)
        if parent is None:
            raise ProcessNotFound(parent_process_id)
        requested = self._normalize_authority(authority)
        if not set(requested).issubset(parent.delegable_authority):
            raise AuthorityViolation("child authority exceeds parent delegable authority")
        child = self.submit("kernel.spawn", authority=requested, delegable_authority=requested, priority=priority)
        def op(conn: sqlite3.Connection) -> Process:
            self._event(conn, child.process_id, "PROCESS_SPAWNED", {"parent_process_id": parent_process_id})
            conn.execute("UPDATE processes SET parent_process_id=? WHERE process_id=?", (parent_process_id, child.process_id))
            conn.execute("UPDATE process_authority SET delegation_package_json=? WHERE process_id=?", (json.dumps(delegation_package or {}, sort_keys=True), child.process_id))
            self._record_cursor(conn)
            return self._load(conn, child.process_id)
        return self.storage.write(op)

    def add_dependency(self, process_id: str, depends_on_process_id: str) -> None:
        if process_id == depends_on_process_id:
            raise DependencyCycle(process_id)
        def op(conn: sqlite3.Connection) -> None:
            if not self._load(conn, process_id) or not self._load(conn, depends_on_process_id):
                raise ProcessNotFound("dependency endpoint")
            frontier = [depends_on_process_id]
            visited: set[str] = set()
            while frontier:
                node = frontier.pop()
                if node == process_id:
                    raise DependencyCycle(f"{process_id}->{depends_on_process_id}")
                if node in visited:
                    continue
                visited.add(node)
                frontier.extend(row["depends_on_process_id"] for row in conn.execute("SELECT depends_on_process_id FROM process_dependencies WHERE process_id=?", (node,)))
            conn.execute("INSERT OR IGNORE INTO process_dependencies(process_id,depends_on_process_id,created_at) VALUES(?,?,?)", (process_id, depends_on_process_id, self._now()))
            self._event(conn, process_id, "PROCESS_DEPENDENCY_ADDED", {"depends_on_process_id": depends_on_process_id})
            self._record_cursor(conn)
        self.storage.write(op)

    def result(self, process_id: str, outputs: dict[str, Any], effects: dict[str, Any] | None = None) -> Process:
        effects = effects or {}
        def op(conn: sqlite3.Connection) -> Process:
            process = self._load(conn, process_id)
            if process is None or ProcessStatus(process.status) not in TERMINAL:
                raise KernelError("PROCESS_MUST_BE_TERMINAL")
            conn.execute("INSERT INTO process_results(process_id,outputs_json,effects_json) VALUES(?,?,?)", (process_id, json.dumps(outputs), json.dumps(effects)))
            return process
        return self.storage.write(op)

    def snapshot(self) -> dict[str, Any]:
        def read(conn: sqlite3.Connection) -> dict[str, Any]:
            rows = conn.execute("SELECT p.*, a.authority_json, a.delegable_authority_json FROM processes p LEFT JOIN process_authority a USING(process_id) ORDER BY p.created_at").fetchall()
            cursor = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM event_journal").fetchone()[0]
            return {"processes": [asdict(self._process(row)) for row in rows], "cursor": cursor}
        return self.storage.write(read)

    def events_after(self, cursor: int) -> dict[str, Any]:
        def read(conn: sqlite3.Connection) -> dict[str, Any]:
            if cursor < 0:
                raise CursorExpired(f"cursor {cursor} expired; fresh snapshot required")
            events = [dict(row) for row in conn.execute("SELECT * FROM event_journal WHERE sequence>? ORDER BY sequence", (cursor,)).fetchall()]
            next_cursor = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM event_journal").fetchone()[0]
            return {"events": events, "cursor": next_cursor}
        return self.storage.write(read)

    def run_scheduler(self, *, max_slices: int = 1) -> list[Process]:
        ran: list[Process] = []
        for _ in range(max_slices):
            item = self.scheduler.next()
            if not item:
                break
            process = self.get(item.process_id)
            if process is None or ProcessStatus(process.status) != ProcessStatus.CREATED:
                continue
            try:
                ran.append(self.transition(item.process_id, ProcessStatus.RUNNING))
            except InvalidTransition:
                continue
        return ran

    def scheduler_metrics(self) -> dict[str, Any]:
        metrics = self.scheduler.metrics()
        metrics["waiting_processes"] = self.storage.write(lambda conn: conn.execute("SELECT COUNT(*) FROM processes WHERE status=?", (ProcessStatus.WAITING,)).fetchone()[0])
        return metrics
