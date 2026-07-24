from pathlib import Path

import pytest

from vesper.kernel import Kernel, ProcessStatus
from vesper.storage import Storage
from vesper.syscalls import (
    ApprovalDecision,
    ApprovalMismatch,
    ApprovalRequired,
    AuthorityDenied,
    Decision,
    EffectBlocked,
    EffectStatus,
    PermissionDenied,
    PermissionRequestState,
    SyscallRequest,
    SyscallEngine,
    UnknownEffect,
)


def runtime(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate()
    storage.start()
    return storage, Kernel(storage)


def close(storage: Storage) -> None:
    storage.stop()


def test_edit_creates_lineage_and_cannot_reuse_original_grant(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    original = SyscallRequest(process.process_id, "test.effect", "a", {"value": "one"})
    edited = SyscallRequest(process.process_id, "test.effect", "b", {"value": "two"})
    old_approval = engine.request_approval(original)
    new_approval = engine.decide(old_approval, ApprovalDecision.EDITED, edited=edited)

    assert new_approval != old_approval
    lineage = engine.approval_lineage(new_approval)
    assert lineage["original_approval_id"] == old_approval
    assert lineage["original_fingerprint"] == original.fingerprint()
    assert lineage["edited_fingerprint"] == edited.fingerprint()
    with pytest.raises(ApprovalMismatch):
        engine.execute(original, approval_id=old_approval)
    with pytest.raises(ApprovalMismatch):
        engine.execute(edited, approval_id=old_approval)
    engine.decide(new_approval, ApprovalDecision.APPROVED)
    assert engine.execute(edited, approval_id=new_approval).status == "COMMITTED"
    close(storage)


def test_edit_revalidates_registration_authority_and_does_not_copy_approval(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    original = SyscallRequest(process.process_id, "test.effect", "allowed", {"value": "x"})
    edited = SyscallRequest(process.process_id, "test.effect", "blocked", {"value": "x"})
    old = engine.request_approval(original)
    new = engine.decide(old, ApprovalDecision.EDITED, edited=edited)
    engine.grant(operation="test.effect", resource_selector="blocked", decision=Decision.DENY)
    engine.decide(new, ApprovalDecision.APPROVED)
    with pytest.raises(AuthorityDenied):
        engine.execute(edited, approval_id=new)
    close(storage)


def test_permission_request_is_bounded_and_denial_is_not_model_reinterpretable(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    request_id = engine.permission_request(
        process_id=process.process_id,
        operation="test.effect",
        resource_selector="narrow",
        requested_uses=1,
    )
    assert engine.decide_permission(request_id, PermissionRequestState.DENIED) is None
    assert engine.permission_status(request_id)["state"] == PermissionRequestState.DENIED
    with pytest.raises(ApprovalRequired):
        engine.execute(SyscallRequest(process.process_id, "test.effect", "narrow", {"value": "x"}))
    close(storage)


def test_permission_grant_cannot_exceed_request_and_use_bound_is_enforced(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    request_id = engine.permission_request(
        process_id=process.process_id,
        operation="test.effect",
        resource_selector="narrow",
        requested_uses=1,
    )
    with pytest.raises(PermissionDenied):
        engine.decide_permission(request_id, PermissionRequestState.GRANTED, resource_selector="broader")
    rule_id = engine.decide_permission(request_id, PermissionRequestState.GRANTED, decision=Decision.ASK, uses_remaining=1)
    assert rule_id
    syscall = SyscallRequest(process.process_id, "test.effect", "narrow", {"value": "x"})
    approval = engine.request_approval(syscall)
    engine.decide(approval, ApprovalDecision.APPROVED)
    assert engine.execute(syscall, approval_id=approval).status == "COMMITTED"
    with pytest.raises(ApprovalRequired):
        engine.execute(syscall)
    close(storage)


def test_revocation_propagates_through_descendant_grant_lineage(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    root = engine.grant(operation="test.effect", resource_selector="*", decision=Decision.ASK, delegable=True)
    child = engine.grant(operation="test.effect", resource_selector="child", decision=Decision.ASK, parent_rule_id=root, delegable=True)
    grandchild = engine.grant(operation="test.effect", resource_selector="child", decision=Decision.ASK, parent_rule_id=child)
    engine.revoke(root)
    rows = storage.write(lambda c: c.execute("SELECT rule_id, revoked_at FROM authority_rules WHERE rule_id IN (?,?,?)", (root, child, grandchild)).fetchall())
    assert all(row["revoked_at"] for row in rows)
    close(storage)


def test_unknown_effect_blocks_duplicate_submission_until_reconciled(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    syscall = SyscallRequest(process.process_id, "test.effect", "x", {"value": "x"})
    approval = engine.request_approval(syscall)
    engine.decide(approval, ApprovalDecision.APPROVED)
    engine.primitives["test.effect"] = lambda _: (_ for _ in ()).throw(TimeoutError())
    with pytest.raises(UnknownEffect) as unknown:
        engine.execute(syscall, approval_id=approval)
    effect_id = str(unknown.value)
    with pytest.raises(EffectBlocked):
        engine.execute(syscall)
    engine.reconcile(effect_id, status=EffectStatus.CONFIRMED_NOT_APPLIED)
    retry_approval = engine.request_approval(syscall)
    engine.decide(retry_approval, ApprovalDecision.APPROVED)
    engine.primitives["test.effect"] = lambda request: {"value": request.args["value"], "effect": "committed"}
    assert engine.execute(syscall, approval_id=retry_approval).status == "COMMITTED"
    close(storage)


def test_secret_values_are_redacted_from_approval_and_effect_records(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    secret = "super-secret-value"
    syscall = SyscallRequest(process.process_id, "test.effect", "x", {"value": secret, "api_key": secret})
    approval = engine.request_approval(syscall)
    payloads = storage.write(lambda c: [row[0] for row in c.execute("SELECT args_json FROM approvals WHERE approval_id=?", (approval,)).fetchall()])
    assert secret not in "".join(payloads)
    close(storage)


def test_restart_preserves_pending_approval_and_unknown_effect(tmp_path: Path):
    db = tmp_path / "vesper.sqlite3"
    storage = Storage(db)
    storage.migrate()
    storage.start()
    kernel = Kernel(storage)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    syscall = SyscallRequest(process.process_id, "test.effect", "x", {"value": "x"})
    pending = engine.request_approval(syscall)
    assert kernel.get(process.process_id).status == ProcessStatus.WAITING
    storage.stop()

    restarted = Storage(db)
    restarted.migrate()
    restarted.start()
    after = SyscallEngine(restarted, Kernel(restarted))
    assert after.approval_status(pending)["decision"] == ApprovalDecision.PENDING
    restarted.stop()
