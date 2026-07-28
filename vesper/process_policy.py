"""Durable, deterministic limits owned by a Process."""
from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Any


@dataclass(frozen=True)
class ProcessPolicy:
    process_id: str
    policy_class: str = "normal"
    max_graph_nodes: int = 64
    max_expansion_depth: int = 8
    max_lane_invocations: int = 32
    max_replan_count: int = 4
    retry_budget: int = 8
    deadline_at: str | None = None
    cost_token_budget: int | None = None
    approval_boundaries: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.process_id:
            raise ValueError("process_id is required")
        if self.policy_class not in {"interactive", "normal", "background", "persistent", "recurring", "monitoring"}:
            raise ValueError("invalid policy_class")
        for name in ("max_graph_nodes", "max_expansion_depth", "max_lane_invocations", "max_replan_count", "retry_budget"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if self.cost_token_budget is not None and self.cost_token_budget < 1:
            raise ValueError("cost_token_budget must be positive")

    def allows_graph(self, *, nodes: int, depth: int, lane_invocations: int, replans: int, retries: int) -> bool:
        return (nodes <= self.max_graph_nodes and depth <= self.max_expansion_depth and
                lane_invocations <= self.max_lane_invocations and replans <= self.max_replan_count and
                retries <= self.retry_budget)

    def requires_approval(self, effect_class: str) -> bool:
        return effect_class in self.approval_boundaries


class ProcessPolicyStore:
    def __init__(self, storage: Any) -> None:
        self.storage = storage

    def create(self, policy: ProcessPolicy) -> ProcessPolicy:
        def write(c: sqlite3.Connection) -> ProcessPolicy:
            c.execute("""INSERT INTO process_policies(process_id,policy_class,max_graph_nodes,max_expansion_depth,max_lane_invocations,max_replan_count,retry_budget,deadline_at,cost_token_budget,approval_boundaries_json) VALUES(?,?,?,?,?,?,?,?,?,?)""", (policy.process_id, policy.policy_class, policy.max_graph_nodes, policy.max_expansion_depth, policy.max_lane_invocations, policy.max_replan_count, policy.retry_budget, policy.deadline_at, policy.cost_token_budget, json.dumps(policy.approval_boundaries)))
            return policy
        return self.storage.write(write)

    def get(self, process_id: str) -> ProcessPolicy | None:
        def read(c: sqlite3.Connection) -> ProcessPolicy | None:
            row = c.execute("SELECT * FROM process_policies WHERE process_id=?", (process_id,)).fetchone()
            if row is None:
                return None
            return ProcessPolicy(process_id=row["process_id"], policy_class=row["policy_class"], max_graph_nodes=row["max_graph_nodes"], max_expansion_depth=row["max_expansion_depth"], max_lane_invocations=row["max_lane_invocations"], max_replan_count=row["max_replan_count"], retry_budget=row["retry_budget"], deadline_at=row["deadline_at"], cost_token_budget=row["cost_token_budget"], approval_boundaries=tuple(json.loads(row["approval_boundaries_json"] or "[]")))
        return self.storage.write(read)

    def _set_status(self, process_id: str, expected: str, target: str) -> str:
        from datetime import datetime, timezone
        def write(c: sqlite3.Connection) -> str:
            row = c.execute("SELECT status FROM processes WHERE process_id=?", (process_id,)).fetchone()
            if row is None:
                raise ValueError("unknown process")
            if row["status"] != expected:
                raise ValueError(f"process must be {expected.lower()}")
            c.execute("UPDATE processes SET status=?,revision=revision+1,updated_at=? WHERE process_id=?", (target, datetime.now(timezone.utc).isoformat(), process_id))
            return target
        return self.storage.write(write)

    def pause(self, process_id: str) -> str:
        return self._set_status(process_id, "RUNNING", "PAUSED")

    def resume(self, process_id: str) -> str:
        return self._set_status(process_id, "PAUSED", "RUNNING")

    def recover_after_crash(self) -> tuple[str, ...]:
        from datetime import datetime, timezone
        def write(c: sqlite3.Connection) -> tuple[str, ...]:
            rows = c.execute("SELECT process_id FROM processes WHERE status IN ('RUNNING','WAITING') ORDER BY process_id").fetchall()
            now = datetime.now(timezone.utc).isoformat()
            for row in rows:
                c.execute("UPDATE processes SET status='PAUSED', revision=revision+1, updated_at=? WHERE process_id=?", (now, row["process_id"]))
            return tuple(row["process_id"] for row in rows)
        return self.storage.write(write)


class ProcessBudget:
    def __init__(self, *, tokens: int, seconds: int) -> None:
        if tokens < 0 or seconds < 0:
            raise ValueError("budgets cannot be negative")
        self.tokens = tokens
        self.seconds = seconds

    def consume(self, *, tokens: int, seconds: int) -> bool:
        if tokens < 0 or seconds < 0 or tokens > self.tokens or seconds > self.seconds:
            return False
        self.tokens -= tokens
        self.seconds -= seconds
        return True

    def replenish(self, *, tokens: int, seconds: int) -> None:
        if tokens < 0 or seconds < 0:
            raise ValueError("replenishment cannot be negative")
        self.tokens += tokens
        self.seconds += seconds


class ProcessTimerStore:
    def __init__(self, storage: Any) -> None:
        self.storage = storage

    def schedule(self, process_id: str, due_at: str, *, wake_key: str) -> None:
        self.storage.write(lambda c: c.execute("INSERT OR REPLACE INTO process_timers(process_id,due_at,wake_key,claimed_at) VALUES(?,?,?,NULL)", (process_id, due_at, wake_key)))

    def due(self, *, now: Any) -> tuple[tuple[str, str], ...]:
        value = now.isoformat() if hasattr(now, "isoformat") else str(now)
        return self.storage.write(lambda c: tuple((row["process_id"], row["wake_key"]) for row in c.execute("SELECT process_id,wake_key FROM process_timers WHERE claimed_at IS NULL AND due_at<=? ORDER BY due_at,process_id", (value,)).fetchall()))

    def claim(self, process_id: str) -> bool:
        from datetime import datetime, timezone
        def write(c: sqlite3.Connection) -> bool:
            cursor = c.execute("UPDATE process_timers SET claimed_at=? WHERE process_id=? AND claimed_at IS NULL", (datetime.now(timezone.utc).isoformat(), process_id))
            return cursor.rowcount == 1
        return self.storage.write(write)


class ProcessRecurrenceStore:
    def __init__(self, storage: Any) -> None:
        self.storage = storage

    def configure(self, process_id: str, *, interval_seconds: int, max_runs: int) -> None:
        if interval_seconds < 1 or max_runs < 1:
            raise ValueError("recurrence bounds must be positive")
        self.storage.write(lambda c: c.execute("INSERT OR REPLACE INTO process_recurrences(process_id,interval_seconds,max_runs,run_count,next_due_at) VALUES(?,?,?,?,NULL)", (process_id, interval_seconds, max_runs, 0)))

    def next_run(self, process_id: str, *, now: str) -> int | None:
        from datetime import datetime, timedelta
        def write(c: sqlite3.Connection) -> int | None:
            row = c.execute("SELECT * FROM process_recurrences WHERE process_id=?", (process_id,)).fetchone()
            if row is None or row["run_count"] >= row["max_runs"]:
                return None
            due = row["next_due_at"]
            if due is not None and now < due:
                return None
            count = int(row["run_count"]) + 1
            next_due = (datetime.fromisoformat(now) + timedelta(seconds=row["interval_seconds"])).isoformat()
            c.execute("UPDATE process_recurrences SET run_count=?,next_due_at=? WHERE process_id=?", (count, next_due, process_id))
            return count
        return self.storage.write(write)


class ProcessMonitor:
    def __init__(self, *, cadence_seconds: int, max_checks: int) -> None:
        self.cadence_seconds, self.max_checks = cadence_seconds, max_checks
        self._last: int | None = None
        self._checks = 0

    def check(self, *, now: int, condition: Any) -> bool | None:
        if self._checks >= self.max_checks or (self._last is not None and now - self._last < self.cadence_seconds):
            return None
        self._last, self._checks = now, self._checks + 1
        return bool(condition())