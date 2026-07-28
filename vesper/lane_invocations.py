"""Durable identity and lifecycle for one bounded Lane execution."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .lanes import LaneRegistry, LaneNotFoundError, LaneVersionNotFoundError
from .storage import Storage
from .adaptive_execution import (
    ContextNeed, GraphRevisionRequest, LaneOutcome, LaneOutcomeDisposition,
    LaneOutcomeValidator, ProposedWorkUnit, WorkExpansionProposal,
)
from .model_runtime import CognitiveRequest, CognitiveRuntime, ModelRoute


class LaneInvocationStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LaneInvocationError(RuntimeError):
    code = "LANE_INVOCATION_ERROR"


class LaneInvocationNotFoundError(LaneInvocationError):
    code = "LANE_INVOCATION_NOT_FOUND"


class LaneInvocationInvalidTransitionError(LaneInvocationError):
    code = "LANE_INVOCATION_INVALID_TRANSITION"


class LaneInvocationProcessNotFoundError(LaneInvocationError):
    code = "LANE_INVOCATION_PROCESS_NOT_FOUND"


class LaneInvocationLaneNotFoundError(LaneInvocationError):
    code = "LANE_INVOCATION_LANE_NOT_FOUND"


class LaneInvocationLaneDisabledError(LaneInvocationError):
    code = "LANE_INVOCATION_LANE_DISABLED"


@dataclass(frozen=True)
class LaneInvocation:
    invocation_id: str
    process_id: str
    lane_id: str
    lane_version: int
    node_id: str | None
    status: LaneInvocationStatus
    input_artifact_refs: tuple[str, ...]
    context_refs: tuple[str, ...]
    tool_grants: tuple[str, ...]
    model_route_id: str | None
    output_artifact_ref: str | None
    failure_classification: dict[str, Any] | None
    created_at: str
    started_at: str | None
    completed_at: str | None


@dataclass(frozen=True)
class LaneExecutionResult:
    invocation: LaneInvocation
    primary_result: dict[str, Any]
    outcome: LaneOutcome


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _from_row(row: sqlite3.Row) -> LaneInvocation:
    return LaneInvocation(
        invocation_id=row["invocation_id"], process_id=row["process_id"], lane_id=row["lane_id"],
        lane_version=row["lane_version"], node_id=row["node_id"], status=LaneInvocationStatus(row["status"]),
        input_artifact_refs=tuple(json.loads(row["input_artifact_refs_json"])), context_refs=tuple(json.loads(row["context_refs_json"])),
        tool_grants=tuple(json.loads(row["tool_grants_json"])), model_route_id=row["model_route_id"], output_artifact_ref=row["output_artifact_ref"],
        failure_classification=json.loads(row["failure_classification_json"]) if row["failure_classification_json"] else None,
        created_at=row["created_at"], started_at=row["started_at"], completed_at=row["completed_at"],
    )


class LaneInvocationStore:
    def __init__(self, storage: Storage, lanes: LaneRegistry) -> None:
        self.storage, self.lanes = storage, lanes
        self.cognitive: CognitiveRuntime | None = None

    def bind_cognitive_runtime(self, cognitive: CognitiveRuntime) -> None:
        self.cognitive = cognitive

    def execute(self, invocation_id: str, input_payload: dict[str, Any], *, route: ModelRoute | None = None) -> LaneExecutionResult:
        if self.cognitive is None:
            raise RuntimeError("cognitive runtime is not bound")
        invocation = self.start(invocation_id)
        definition = self.lanes.get(invocation.lane_id, invocation.lane_version)
        contract = {"lane": {"lane_id": definition.lane_id, "version": definition.version, "purpose": definition.purpose, "input_schema": definition.input_schema, "output_schema": definition.output_schema, "context_policy": definition.context_policy}, "input": input_payload}
        response = self.cognitive.invoke_model(invocation.process_id, CognitiveRequest(), contract, route=route)
        if not response.success or not response.output:
            failed = self.fail(invocation_id, {"classification": response.response.error or "MODEL_ERROR", "reason": "provider failure"})
            raise ValueError("lane provider invocation failed")
        try:
            value = json.loads(response.output)
            if not isinstance(value, dict) or not isinstance(value.get("result"), dict) or not isinstance(value.get("outcome"), dict):
                raise ValueError("lane output must contain result and outcome objects")
            disposition = LaneOutcomeDisposition(value["outcome"].get("disposition"))
            raw_control = value["outcome"].get("control_request")
            control = raw_control
            if disposition == LaneOutcomeDisposition.NEED_CONTEXT:
                control = ContextNeed(raw_control["reason"], tuple(raw_control.get("requested_refs_or_kinds", ())))
            elif disposition == LaneOutcomeDisposition.EXPAND:
                units = tuple(ProposedWorkUnit(u["unit_id"], u["lane_id"], u["objective"], tuple(u.get("depends_on", ()))) for u in raw_control["proposed_work_units"])
                control = WorkExpansionProposal(raw_control["reason"], units)
            elif disposition == LaneOutcomeDisposition.REPLAN:
                control = GraphRevisionRequest(raw_control["reason"], tuple(raw_control.get("new_evidence_refs", ())), tuple(raw_control.get("invalidated_assumptions", ())))
            outcome = LaneOutcome(disposition, control_request=control)
            LaneOutcomeValidator.validate(outcome)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.fail(invocation_id, {"classification": "MALFORMED_OUTPUT", "reason": str(exc)})
            raise ValueError("malformed lane provider output") from exc
        completed = self.complete(invocation_id)
        return LaneExecutionResult(completed, value["result"], outcome)

    def create(self, process_id: str, lane_id: str, *, version: int | None = None, node_id: str | None = None,
               input_artifact_refs=(), context_refs=(), tool_grants=(), model_route_id: str | None = None) -> LaneInvocation:
        def operation(conn: sqlite3.Connection):
            if conn.execute("SELECT 1 FROM processes WHERE process_id=?", (process_id,)).fetchone() is None:
                raise LaneInvocationProcessNotFoundError("process not found")
            if version is None:
                row = conn.execute("SELECT * FROM lane_definitions WHERE lane_id=? AND enabled=1 ORDER BY version DESC LIMIT 1", (lane_id,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM lane_definitions WHERE lane_id=? AND version=?", (lane_id, version)).fetchone()
            if row is None:
                raise LaneInvocationLaneNotFoundError("lane version not found")
            if not row["enabled"]:
                raise LaneInvocationLaneDisabledError("lane version is disabled")
            invocation_id, created_at = str(uuid.uuid4()), _now()
            conn.execute("""INSERT INTO lane_invocations
                (invocation_id,process_id,lane_id,lane_version,node_id,status,input_artifact_refs_json,context_refs_json,tool_grants_json,model_route_id,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (invocation_id, process_id, row["lane_id"], row["version"], node_id,
                LaneInvocationStatus.CREATED, _json(list(input_artifact_refs)), _json(list(context_refs)), _json(list(tool_grants)), model_route_id, created_at))
            return conn.execute("SELECT * FROM lane_invocations WHERE invocation_id=?", (invocation_id,)).fetchone()
        return _from_row(self.storage.write(operation))

    def get(self, invocation_id: str) -> LaneInvocation:
        row = self.storage.write(lambda c: c.execute("SELECT * FROM lane_invocations WHERE invocation_id=?", (invocation_id,)).fetchone())
        if row is None: raise LaneInvocationNotFoundError("lane invocation not found")
        return _from_row(row)

    def list(self, process_id: str | None = None) -> list[LaneInvocation]:
        query = "SELECT * FROM lane_invocations" + (" WHERE process_id=?" if process_id else "") + " ORDER BY created_at"
        rows = self.storage.write(lambda c: c.execute(query, (process_id,) if process_id else ()).fetchall())
        return [_from_row(row) for row in rows]

    def _transition(self, invocation_id: str, target: LaneInvocationStatus, **updates: Any) -> LaneInvocation:
        allowed = {LaneInvocationStatus.CREATED: {LaneInvocationStatus.RUNNING, LaneInvocationStatus.CANCELLED}, LaneInvocationStatus.RUNNING: {LaneInvocationStatus.COMPLETED, LaneInvocationStatus.FAILED, LaneInvocationStatus.CANCELLED}}
        def operation(conn: sqlite3.Connection):
            row = conn.execute("SELECT * FROM lane_invocations WHERE invocation_id=?", (invocation_id,)).fetchone()
            if row is None: raise LaneInvocationNotFoundError("lane invocation not found")
            current = LaneInvocationStatus(row["status"])
            if target not in allowed.get(current, set()): raise LaneInvocationInvalidTransitionError(f"{current} -> {target} is invalid")
            fields = {"status": target, **updates}
            conn.execute(f"UPDATE lane_invocations SET {','.join(f'{key}=?' for key in fields)} WHERE invocation_id=?", (*fields.values(), invocation_id))
            return conn.execute("SELECT * FROM lane_invocations WHERE invocation_id=?", (invocation_id,)).fetchone()
        return _from_row(self.storage.write(operation))

    def start(self, invocation_id: str) -> LaneInvocation: return self._transition(invocation_id, LaneInvocationStatus.RUNNING, started_at=_now())
    def complete(self, invocation_id: str, output_artifact_ref: str | None = None) -> LaneInvocation: return self._transition(invocation_id, LaneInvocationStatus.COMPLETED, output_artifact_ref=output_artifact_ref, completed_at=_now())
    def fail(self, invocation_id: str, failure_classification: dict[str, Any]) -> LaneInvocation: return self._transition(invocation_id, LaneInvocationStatus.FAILED, failure_classification_json=_json(failure_classification), completed_at=_now())
    def cancel(self, invocation_id: str) -> LaneInvocation: return self._transition(invocation_id, LaneInvocationStatus.CANCELLED, completed_at=_now())
