"""Kernel-owned syscall ABI, authority checks, approvals, permission requests, and effect reconciliation."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable

from .kernel import Kernel, ProcessStatus, WaitReason
from .storage import Storage


class Decision(StrEnum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


class ApprovalDecision(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"


class PermissionRequestState(StrEnum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class EffectStatus(StrEnum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    UNKNOWN_EFFECT = "UNKNOWN_EFFECT"
    CONFIRMED_APPLIED = "CONFIRMED_APPLIED"
    CONFIRMED_NOT_APPLIED = "CONFIRMED_NOT_APPLIED"
    STILL_UNKNOWN = "STILL_UNKNOWN"
    REJECTED = "REJECTED"
    # Compatibility alias for prior Phase 3 callers.
    RECONCILED = "CONFIRMED_APPLIED"


class SyscallError(RuntimeError):
    code = "SYSCALL_ERROR"


class NotRegistered(SyscallError):
    code = "SYSCALL_NOT_REGISTERED"


class AuthorityDenied(SyscallError):
    code = "AUTHORITY_DENIED"


class ApprovalRequired(SyscallError):
    code = "APPROVAL_REQUIRED"


class ApprovalMismatch(SyscallError):
    code = "APPROVAL_MISMATCH"


class PermissionDenied(SyscallError):
    code = "PERMISSION_DENIED"


class UnknownEffect(SyscallError):
    code = "UNKNOWN_EFFECT"


class EffectBlocked(SyscallError):
    code = "UNKNOWN_EFFECT_BLOCKED"


_SENSITIVE_KEYS = frozenset({"api_key", "apikey", "authorization", "credential", "password", "secret", "token", "access_token", "refresh_token"})


def _redact(value: Any, *, key: str | None = None, approval: bool = False) -> Any:
    if key and (key.lower() in _SENSITIVE_KEYS or any(part in key.lower() for part in ("secret", "token", "password", "api_key", "credential"))):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, key=str(item_key), approval=approval) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item, approval=approval) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, approval=approval) for item in value]
    if approval and isinstance(value, str):
        return "[REDACTED]"
    return value


@dataclass(frozen=True)
class SyscallRequest:
    process_id: str
    operation: str
    target: str
    args: dict[str, Any]
    precondition: dict[str, Any] | None = None
    actor: str = "model"

    def normalized(self) -> dict[str, Any]:
        # Trusted process identity and actor remain kernel-owned and excluded from model fingerprint input.
        return {"operation": self.operation, "target": self.target, "args": self.args, "precondition": self.precondition or {}}

    def fingerprint(self) -> str:
        value = json.dumps(self.normalized(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class SyscallResult:
    status: str
    output: dict[str, Any]
    effect_id: str | None = None
    approval_id: str | None = None


class SyscallEngine:
    def __init__(self, storage: Storage, kernel: Kernel):
        self.storage = storage
        self.kernel = kernel
        self.primitives: dict[str, Callable[[SyscallRequest], dict[str, Any]]] = {
            "test.echo": lambda request: {"message": request.args["message"]},
            "test.effect": lambda request: {"value": request.args["value"], "effect": "committed"},
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def register(self, operation: str, namespace: str, schema: dict[str, Any], risk: str, exposure: str = "REGISTERED") -> None:
        self.storage.write(lambda c: c.execute(
            "INSERT OR REPLACE INTO syscall_registry(operation,namespace,schema_json,risk,exposure) VALUES(?,?,?,?,?)",
            (operation, namespace, json.dumps(schema, sort_keys=True), risk, exposure),
        ))

    def grant(
        self,
        *,
        operation: str,
        resource_selector: str,
        decision: Decision,
        issuer: str = "director",
        delegable: bool = False,
        rule_id: str | None = None,
        parent_rule_id: str | None = None,
        uses_remaining: int | None = None,
    ) -> str:
        rid = rule_id or str(uuid.uuid4())

        def op(c: sqlite3.Connection) -> str:
            if parent_rule_id:
                parent = c.execute("SELECT * FROM authority_rules WHERE rule_id=? AND revoked_at IS NULL", (parent_rule_id,)).fetchone()
                if not parent or not bool(parent["delegable"]):
                    raise PermissionDenied("parent grant is not delegable")
                if parent["operation"] != operation:
                    raise PermissionDenied("child operation exceeds parent grant")
                if parent["resource_selector"] != "*" and parent["resource_selector"] != resource_selector:
                    raise PermissionDenied("child selector exceeds parent grant")
                if parent["decision"] == Decision.DENY or decision == Decision.ALLOW and parent["decision"] != Decision.ALLOW:
                    raise PermissionDenied("child decision exceeds parent grant")
                if parent["uses_remaining"] is not None and (uses_remaining is None or uses_remaining > parent["uses_remaining"]):
                    raise PermissionDenied("child use limit exceeds parent grant")
            c.execute(
                "INSERT OR REPLACE INTO authority_rules(rule_id,operation,resource_selector,decision,issuer,delegable,parent_rule_id,uses_remaining) VALUES(?,?,?,?,?,?,?,?)",
                (rid, operation, resource_selector, decision, issuer, int(delegable), parent_rule_id, uses_remaining),
            )
            return rid

        return self.storage.write(op)

    def revoke(self, rule_id: str) -> None:
        def op(c: sqlite3.Connection) -> None:
            frontier = [rule_id]
            seen: set[str] = set()
            while frontier:
                current = frontier.pop()
                if current in seen:
                    continue
                seen.add(current)
                frontier.extend(row["rule_id"] for row in c.execute("SELECT rule_id FROM authority_rules WHERE parent_rule_id=?", (current,)))
            if seen:
                placeholders = ",".join("?" for _ in seen)
                c.execute(f"UPDATE authority_rules SET revoked_at=? WHERE rule_id IN ({placeholders})", (self._now(), *sorted(seen)))

        self.storage.write(op)

    def _validate_registered(self, c: sqlite3.Connection, request: SyscallRequest) -> None:
        row = c.execute("SELECT * FROM syscall_registry WHERE operation=?", (request.operation,)).fetchone()
        if not row or row["exposure"] not in {"ELIGIBLE", "EXPOSED"}:
            raise NotRegistered(request.operation)
        schema = json.loads(row["schema_json"])
        missing = [key for key in schema.get("required", []) if key not in request.args]
        if missing:
            raise SyscallError(f"missing arguments: {','.join(missing)}")

    def _decision(self, c: sqlite3.Connection, request: SyscallRequest) -> tuple[Decision, sqlite3.Row | None]:
        rows = c.execute(
            "SELECT * FROM authority_rules WHERE operation=? AND revoked_at IS NULL "
            "AND (resource_selector='*' OR resource_selector=?) "
            "AND (uses_remaining IS NULL OR uses_remaining > 0) "
            "ORDER BY resource_selector='*' ASC, issuer='director' DESC",
            (request.operation, request.target),
        ).fetchall()
        if not rows:
            return Decision.DENY, None
        return Decision(rows[0]["decision"]), rows[0]

    def _request_wait(self, process_id: str, wake_key: str) -> None:
        process = self.kernel.get(process_id)
        if process is None:
            return
        if ProcessStatus(process.status) == ProcessStatus.RUNNING:
            self.kernel.wait(process_id, WaitReason.APPROVAL, wake_key=wake_key)
        elif ProcessStatus(process.status) == ProcessStatus.CREATED:
            self.kernel.transition(process_id, ProcessStatus.WAITING)

    def request_approval(self, request: SyscallRequest, *, parent_approval_id: str | None = None) -> str:
        aid = str(uuid.uuid4())

        def op(c: sqlite3.Connection) -> str:
            parent = None
            if parent_approval_id:
                parent = c.execute("SELECT * FROM approvals WHERE approval_id=?", (parent_approval_id,)).fetchone()
                if not parent:
                    raise ApprovalMismatch(parent_approval_id)
            root_id = parent["root_approval_id"] or parent["approval_id"] if parent else aid
            lineage = {
                "original_approval_id": root_id,
                "original_fingerprint": parent["syscall_fingerprint"] if parent else request.fingerprint(),
                "edited_fingerprint": request.fingerprint(),
            }
            c.execute(
                "INSERT INTO approvals(approval_id,process_id,syscall_fingerprint,operation,target,args_json,precondition_json,decision,parent_approval_id,root_approval_id,lineage_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    aid, request.process_id, request.fingerprint(), request.operation, request.target,
                    json.dumps(_redact(request.args, approval=True), sort_keys=True), json.dumps(_redact(request.precondition or {}, approval=True), sort_keys=True),
                    ApprovalDecision.PENDING, parent_approval_id, root_id, json.dumps(lineage, sort_keys=True),
                ),
            )
            return aid

        result = self.storage.write(op)
        self._request_wait(request.process_id, result)
        return result

    def approval_status(self, approval_id: str) -> dict[str, Any]:
        row = self.storage.write(lambda c: c.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone())
        if not row:
            raise ApprovalMismatch(approval_id)
        return dict(row)

    def approval_lineage(self, approval_id: str) -> dict[str, Any]:
        row = self.approval_status(approval_id)
        return json.loads(row["lineage_json"])

    def decide(self, approval_id: str, decision: ApprovalDecision, *, edited: SyscallRequest | None = None) -> str:
        if decision == ApprovalDecision.EDITED:
            if edited is None:
                raise ApprovalMismatch("edit requires request")
            def mark_edited(c: sqlite3.Connection) -> None:
                row = c.execute("SELECT * FROM approvals WHERE approval_id=? AND decision='PENDING'", (approval_id,)).fetchone()
                if not row:
                    raise ApprovalMismatch(approval_id)
                c.execute("UPDATE approvals SET decision='EDITED' WHERE approval_id=?", (approval_id,))
            self.storage.write(mark_edited)
            return self.request_approval(edited, parent_approval_id=approval_id)

        def op(c: sqlite3.Connection) -> tuple[str, str]:
            row = c.execute("SELECT * FROM approvals WHERE approval_id=? AND decision='PENDING'", (approval_id,)).fetchone()
            if not row:
                raise ApprovalMismatch(approval_id)
            c.execute("UPDATE approvals SET decision=? WHERE approval_id=?", (decision, approval_id))
            return approval_id, row["process_id"]

        result, process_id = self.storage.write(op)
        if decision == ApprovalDecision.APPROVED:
            self.kernel.wake(approval_id)
        elif decision == ApprovalDecision.REJECTED:
            process = self.kernel.get(process_id)
            if process and ProcessStatus(process.status) == ProcessStatus.WAITING:
                self.kernel.transition(process_id, ProcessStatus.CANCELLED)
        return result

    def permission_request(self, *, process_id: str, operation: str, resource_selector: str, requested_uses: int | None = None) -> str:
        request_id = str(uuid.uuid4())
        self.storage.write(lambda c: c.execute(
            "INSERT INTO permission_requests(request_id,process_id,operation,resource_selector,requested_uses,state) VALUES(?,?,?,?,?,?)",
            (request_id, process_id, operation, resource_selector, requested_uses, PermissionRequestState.PENDING),
        ))
        self._request_wait(process_id, request_id)
        return request_id

    def permission_status(self, request_id: str) -> dict[str, Any]:
        row = self.storage.write(lambda c: c.execute("SELECT * FROM permission_requests WHERE request_id=?", (request_id,)).fetchone())
        if not row:
            raise PermissionDenied(request_id)
        return dict(row)

    def decide_permission(
        self,
        request_id: str,
        state: PermissionRequestState,
        *,
        decision: Decision = Decision.ASK,
        resource_selector: str | None = None,
        uses_remaining: int | None = None,
    ) -> str | None:
        if state not in {PermissionRequestState.GRANTED, PermissionRequestState.DENIED}:
            raise PermissionDenied("invalid permission decision")

        def op(c: sqlite3.Connection) -> tuple[sqlite3.Row, str | None]:
            row = c.execute("SELECT * FROM permission_requests WHERE request_id=? AND state='PENDING'", (request_id,)).fetchone()
            if not row:
                raise PermissionDenied(request_id)
            selector = resource_selector or row["resource_selector"]
            if selector != row["resource_selector"]:
                raise PermissionDenied("grant selector exceeds explicit request")
            if state == PermissionRequestState.GRANTED and row["requested_uses"] is not None and (uses_remaining is None or uses_remaining > row["requested_uses"]):
                raise PermissionDenied("grant use limit exceeds explicit request")
            rule_id = None
            if state == PermissionRequestState.GRANTED:
                rule_id = str(uuid.uuid4())
                c.execute(
                    "INSERT INTO authority_rules(rule_id,operation,resource_selector,decision,issuer,delegable,uses_remaining) VALUES(?,?,?,?,?,?,?)",
                    (rule_id, row["operation"], selector, decision, "director", 0, uses_remaining),
                )
            c.execute(
                "UPDATE permission_requests SET state=?,granted_rule_id=?,decided_at=? WHERE request_id=?",
                (state, rule_id, self._now(), request_id),
            )
            return row, rule_id

        request, rule_id = self.storage.write(op)
        if state == PermissionRequestState.GRANTED:
            self.kernel.wake(request_id)
        return rule_id

    def execute(self, request: SyscallRequest, *, approval_id: str | None = None) -> SyscallResult:
        def reserve(c: sqlite3.Connection) -> tuple[sqlite3.Row | None, str | None]:
            self._validate_registered(c, request)
            unknown = c.execute(
                "SELECT effect_id FROM effects WHERE process_id=? AND operation=? AND fingerprint=? "
                "AND status IN ('UNKNOWN_EFFECT','STILL_UNKNOWN')",
                (request.process_id, request.operation, request.fingerprint()),
            ).fetchone()
            if unknown:
                raise EffectBlocked(unknown["effect_id"])
            decision, rule = self._decision(c, request)
            approval = None
            if decision == Decision.DENY:
                raise AuthorityDenied(request.operation)
            if decision == Decision.ASK:
                if not approval_id:
                    raise ApprovalRequired(request.operation)
                approval = c.execute("SELECT * FROM approvals WHERE approval_id=? AND process_id=?", (approval_id, request.process_id)).fetchone()
                if not approval or approval["syscall_fingerprint"] != request.fingerprint() or approval["decision"] != ApprovalDecision.APPROVED or (approval["one_shot"] and approval["consumed_at"]):
                    raise ApprovalMismatch(approval_id or "missing")
            effect_id = str(uuid.uuid4()) if request.operation != "test.echo" else None
            if effect_id:
                c.execute(
                    "INSERT INTO effects(effect_id,process_id,operation,fingerprint,status) VALUES(?,?,?,?,?)",
                    (effect_id, request.process_id, request.operation, request.fingerprint(), EffectStatus.RESERVED),
                )
            if approval:
                c.execute("UPDATE approvals SET consumed_at=? WHERE approval_id=?", (self._now(), approval_id))
            if rule and rule["uses_remaining"] is not None:
                updated = c.execute(
                    "UPDATE authority_rules SET uses_remaining=uses_remaining-1 WHERE rule_id=? AND uses_remaining>0",
                    (rule["rule_id"],),
                )
                if updated.rowcount != 1:
                    raise AuthorityDenied(request.operation)
            return approval, effect_id

        _, effect_id = self.storage.write(reserve)
        try:
            primitive = self.primitives.get(request.operation)
            if primitive is None:
                raise NotRegistered(request.operation)
            output = primitive(request)
        except TimeoutError:
            if effect_id:
                self.storage.write(lambda c: c.execute(
                    "UPDATE effects SET status=?,updated_at=? WHERE effect_id=?",
                    (EffectStatus.UNKNOWN_EFFECT, self._now(), effect_id),
                ))
            raise UnknownEffect(effect_id or request.operation)
        if effect_id:
            self.storage.write(lambda c: c.execute(
                "UPDATE effects SET status=?,output_json=?,updated_at=? WHERE effect_id=?",
                (EffectStatus.COMMITTED, json.dumps(_redact(output), sort_keys=True), self._now(), effect_id),
            ))
        if approval_id:
            process = self.kernel.get(request.process_id)
            if process and ProcessStatus(process.status) == ProcessStatus.WAITING:
                self.kernel.wake(approval_id)
        return SyscallResult(status="COMMITTED", output=output, effect_id=effect_id, approval_id=approval_id)

    def reconcile(self, effect_id: str, *, status: EffectStatus, output: dict[str, Any] | None = None) -> None:
        if status not in {EffectStatus.CONFIRMED_APPLIED, EffectStatus.CONFIRMED_NOT_APPLIED, EffectStatus.STILL_UNKNOWN, EffectStatus.REJECTED}:
            raise SyscallError("invalid reconciliation status")

        def op(c: sqlite3.Connection) -> None:
            row = c.execute("SELECT status FROM effects WHERE effect_id=?", (effect_id,)).fetchone()
            if not row or row["status"] not in {EffectStatus.UNKNOWN_EFFECT, EffectStatus.STILL_UNKNOWN}:
                raise SyscallError("effect is not reconcilable")
            c.execute(
                "UPDATE effects SET status=?,output_json=?,updated_at=? WHERE effect_id=?",
                (status, json.dumps(_redact(output or {}), sort_keys=True), self._now(), effect_id),
            )

        self.storage.write(op)
        if status == EffectStatus.CONFIRMED_APPLIED:
            effect = self.storage.write(lambda c: c.execute("SELECT process_id FROM effects WHERE effect_id=?", (effect_id,)).fetchone())
            if effect:
                process = self.kernel.get(effect["process_id"])
                if process and ProcessStatus(process.status) == ProcessStatus.WAITING:
                    self.kernel.wake(effect_id)
                    current = self.kernel.get(effect["process_id"])
                    if current and ProcessStatus(current.status) == ProcessStatus.WAITING:
                        self.kernel.transition(effect["process_id"], ProcessStatus.RUNNING)
