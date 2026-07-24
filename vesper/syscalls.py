"""Kernel-owned syscall ABI, authority checks, exact approvals, and effect reconciliation."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable

from .kernel import Kernel
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


class EffectStatus(StrEnum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    UNKNOWN_EFFECT = "UNKNOWN_EFFECT"
    RECONCILED = "RECONCILED"
    REJECTED = "REJECTED"


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


class UnknownEffect(SyscallError):
    code = "UNKNOWN_EFFECT"


@dataclass(frozen=True)
class SyscallRequest:
    process_id: str
    operation: str
    target: str
    args: dict[str, Any]
    precondition: dict[str, Any] | None = None
    actor: str = "model"

    def normalized(self) -> dict[str, Any]:
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
        self.storage.write(lambda c: c.execute("INSERT OR REPLACE INTO syscall_registry(operation,namespace,schema_json,risk,exposure) VALUES(?,?,?,?,?)", (operation, namespace, json.dumps(schema, sort_keys=True), risk, exposure)))

    def grant(self, *, operation: str, resource_selector: str, decision: Decision, issuer: str = "director", delegable: bool = False, rule_id: str | None = None, parent_rule_id: str | None = None) -> str:
        rid = rule_id or str(uuid.uuid4())
        self.storage.write(lambda c: c.execute("INSERT OR REPLACE INTO authority_rules(rule_id,operation,resource_selector,decision,issuer,delegable,parent_rule_id) VALUES(?,?,?,?,?,?,?)", (rid, operation, resource_selector, decision, issuer, int(delegable), parent_rule_id)))
        return rid

    def revoke(self, rule_id: str) -> None:
        self.storage.write(lambda c: c.execute("UPDATE authority_rules SET revoked_at=? WHERE rule_id=? OR parent_rule_id=?", (self._now(), rule_id, rule_id)))

    def _validate_registered(self, c: sqlite3.Connection, request: SyscallRequest) -> None:
        row = c.execute("SELECT * FROM syscall_registry WHERE operation=?", (request.operation,)).fetchone()
        if not row or row["exposure"] not in {"ELIGIBLE", "EXPOSED"}:
            raise NotRegistered(request.operation)
        schema = json.loads(row["schema_json"])
        missing = [key for key in schema.get("required", []) if key not in request.args]
        if missing:
            raise SyscallError(f"missing arguments: {','.join(missing)}")

    def _decision(self, c: sqlite3.Connection, request: SyscallRequest) -> Decision:
        rows = c.execute("SELECT * FROM authority_rules WHERE operation=? AND revoked_at IS NULL AND (resource_selector='*' OR resource_selector=?) ORDER BY resource_selector='*' ASC, issuer='director' DESC", (request.operation, request.target)).fetchall()
        if not rows:
            return Decision.DENY
        return Decision(rows[0]["decision"])

    def request_approval(self, request: SyscallRequest) -> str:
        aid = str(uuid.uuid4())
        self.storage.write(lambda c: c.execute("INSERT INTO approvals(approval_id,process_id,syscall_fingerprint,operation,target,args_json,precondition_json,decision) VALUES(?,?,?,?,?,?,?,?)", (aid, request.process_id, request.fingerprint(), request.operation, request.target, json.dumps(request.args, sort_keys=True), json.dumps(request.precondition or {}, sort_keys=True), ApprovalDecision.PENDING)))
        from .kernel import ProcessStatus
        self.kernel.transition(request.process_id, ProcessStatus.WAITING)
        return aid

    def decide(self, approval_id: str, decision: ApprovalDecision, *, edited: SyscallRequest | None = None) -> str:
        def op(c: sqlite3.Connection) -> str:
            row = c.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if not row:
                raise ApprovalMismatch(approval_id)
            if decision == ApprovalDecision.EDITED:
                if edited is None:
                    raise ApprovalMismatch("edit requires request")
                new_id = str(uuid.uuid4())
                c.execute("UPDATE approvals SET decision='EDITED' WHERE approval_id=?", (approval_id,))
                c.execute("INSERT INTO approvals(approval_id,process_id,syscall_fingerprint,operation,target,args_json,precondition_json,decision) VALUES(?,?,?,?,?,?,?,?)", (new_id, edited.process_id, edited.fingerprint(), edited.operation, edited.target, json.dumps(edited.args, sort_keys=True), json.dumps(edited.precondition or {}, sort_keys=True), ApprovalDecision.PENDING))
                return new_id
            c.execute("UPDATE approvals SET decision=? WHERE approval_id=? AND decision='PENDING'", (decision, approval_id))
            return approval_id
        return self.storage.write(op)

    def execute(self, request: SyscallRequest, *, approval_id: str | None = None) -> SyscallResult:
        def reserve(c: sqlite3.Connection) -> tuple[Decision, sqlite3.Row | None, str | None]:
            self._validate_registered(c, request)
            decision = self._decision(c, request)
            approval = None
            if decision == Decision.DENY:
                raise AuthorityDenied(request.operation)
            if decision == Decision.ASK:
                if not approval_id:
                    raise ApprovalRequired(request.operation)
                approval = c.execute("SELECT * FROM approvals WHERE approval_id=? AND process_id=?", (approval_id, request.process_id)).fetchone()
                if not approval or approval["syscall_fingerprint"] != request.fingerprint() or approval["decision"] != ApprovalDecision.APPROVED or (approval["one_shot"] and approval["consumed_at"]):
                    raise ApprovalMismatch(approval_id or "missing")
            effect_id = str(uuid.uuid4()) if request.operation == "test.effect" else None
            if effect_id:
                c.execute("INSERT INTO effects(effect_id,process_id,operation,fingerprint,status) VALUES(?,?,?,?,?)", (effect_id, request.process_id, request.operation, request.fingerprint(), EffectStatus.RESERVED))
                if approval:
                    c.execute("UPDATE approvals SET consumed_at=? WHERE approval_id=?", (self._now(), approval_id))
            return decision, approval, effect_id
        _, _, effect_id = self.storage.write(reserve)
        try:
            output = self.primitives[request.operation](request)
        except TimeoutError:
            if effect_id:
                self.storage.write(lambda c: c.execute("UPDATE effects SET status=?,updated_at=? WHERE effect_id=?", (EffectStatus.UNKNOWN_EFFECT, self._now(), effect_id)))
            raise UnknownEffect(effect_id or request.operation)
        if effect_id:
            self.storage.write(lambda c: c.execute("UPDATE effects SET status=?,output_json=?,updated_at=? WHERE effect_id=?", (EffectStatus.COMMITTED, json.dumps(output, sort_keys=True), self._now(), effect_id)))
        return SyscallResult(status="COMMITTED", output=output, effect_id=effect_id, approval_id=approval_id)

    def reconcile(self, effect_id: str, *, status: EffectStatus, output: dict[str, Any] | None = None) -> None:
        if status not in {EffectStatus.RECONCILED, EffectStatus.COMMITTED, EffectStatus.REJECTED}:
            raise SyscallError("invalid reconciliation status")
        self.storage.write(lambda c: c.execute("UPDATE effects SET status=?,output_json=?,updated_at=? WHERE effect_id=? AND status='UNKNOWN_EFFECT'", (status, json.dumps(output or {}, sort_keys=True), self._now(), effect_id)))
####Tool(namespace=