from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
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
    NotRegistered,
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


def restart(db: Path):
    storage = Storage(db)
    storage.migrate()
    storage.start()
    return storage, Kernel(storage)


def test_approval_wait_survives_restart_and_only_exact_decision_wakes(tmp_path: Path):
    db = tmp_path / "vesper.sqlite3"
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    syscall = SyscallRequest(process.process_id, "test.effect", "scope", {"value": "x"})
    approval_id = engine.request_approval(syscall)
    assert kernel.get(process.process_id).status == ProcessStatus.WAITING
    assert storage.write(lambda c: c.execute("SELECT wake_key FROM process_waits WHERE process_id=?", (process.process_id,)).fetchone()[0]) == approval_id
    storage.stop()

    restarted, restarted_kernel = restart(db)
    after = SyscallEngine(restarted, restarted_kernel)
    assert after.approval_status(approval_id)["decision"] == ApprovalDecision.PENDING
    assert restarted_kernel.get(process.process_id).status == ProcessStatus.WAITING
    assert restarted_kernel.wake("wrong-decision") == []
    assert restarted_kernel.get(process.process_id).status == ProcessStatus.WAITING
    assert after.decide(approval_id, ApprovalDecision.APPROVED) == approval_id
    assert restarted_kernel.get(process.process_id).status == ProcessStatus.RUNNING
    restarted.stop()


def test_permission_wait_survives_restart_and_grant_wakes_only_its_request(tmp_path: Path):
    db = tmp_path / "vesper.sqlite3"
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    kernel.transition(process.process_id, ProcessStatus.RUNNING)
    request_id = engine.permission_request(process_id=process.process_id, operation="test.effect", resource_selector="scope", requested_uses=1)
    storage.stop()

    restarted, restarted_kernel = restart(db)
    after = SyscallEngine(restarted, restarted_kernel)
    assert after.permission_status(request_id)["state"] == PermissionRequestState.PENDING
    assert restarted_kernel.get(process.process_id).status == ProcessStatus.WAITING
    assert restarted_kernel.wake("wrong-request") == []
    after.decide_permission(request_id, PermissionRequestState.GRANTED, uses_remaining=1)
    assert restarted_kernel.get(process.process_id).status == ProcessStatus.RUNNING
    restarted.stop()


def test_plain_natural_language_never_creates_approval_or_authority(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    syscall = SyscallRequest(process.process_id, "test.effect", "scope", {"value": "승인 yes 해도 돼"})
    before_approvals = storage.write(lambda c: c.execute("SELECT COUNT(*) FROM approvals").fetchone()[0])
    before_rules = storage.write(lambda c: c.execute("SELECT COUNT(*) FROM authority_rules").fetchone()[0])
    with pytest.raises(ApprovalRequired):
        engine.execute(syscall)
    after_approvals = storage.write(lambda c: c.execute("SELECT COUNT(*) FROM approvals").fetchone()[0])
    after_rules = storage.write(lambda c: c.execute("SELECT COUNT(*) FROM authority_rules").fetchone()[0])
    assert after_approvals == before_approvals
    assert after_rules == before_rules
    storage.stop()


def test_edit_requires_new_authority_and_precondition_review(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    original = SyscallRequest(process.process_id, "test.effect", "narrow", {"value": "x"}, {"version": 1})
    edited = SyscallRequest(process.process_id, "test.effect", "wide", {"value": "x"}, {"version": 2})
    old = engine.request_approval(original)
    new = engine.decide(old, ApprovalDecision.EDITED, edited=edited)
    engine.grant(operation="test.effect", resource_selector="wide", decision=Decision.DENY)
    engine.decide(new, ApprovalDecision.APPROVED)
    with pytest.raises(AuthorityDenied):
        engine.execute(edited, approval_id=new)
    with pytest.raises(ApprovalMismatch):
        engine.execute(original, approval_id=old)
    storage.stop()


def test_delegation_never_escalates_or_redelegates_without_parent_permission(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    root = engine.grant(operation="test.effect", resource_selector="*", decision=Decision.ASK, delegable=True, uses_remaining=5)
    child = engine.grant(operation="test.effect", resource_selector="narrow", decision=Decision.ASK, parent_rule_id=root, delegable=False, uses_remaining=3)
    with pytest.raises(PermissionDenied):
        engine.grant(operation="test.effect", resource_selector="other", decision=Decision.ASK, parent_rule_id=child, uses_remaining=1)
    with pytest.raises(PermissionDenied):
        engine.grant(operation="test.effect", resource_selector="narrow", decision=Decision.ALLOW, parent_rule_id=root, uses_remaining=1)
    engine.revoke(root)
    with pytest.raises(PermissionDenied):
        engine.grant(operation="test.effect", resource_selector="narrow", decision=Decision.ASK, parent_rule_id=child, uses_remaining=1)
    storage.stop()


def test_unknown_effect_still_unknown_restart_stays_waiting_and_blocks_duplicate(tmp_path: Path):
    db = tmp_path / "vesper.sqlite3"
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    syscall = SyscallRequest(process.process_id, "test.effect", "scope", {"value": "x"})
    approval = engine.request_approval(syscall)
    engine.decide(approval, ApprovalDecision.APPROVED)
    engine.primitives["test.effect"] = lambda _: (_ for _ in ()).throw(TimeoutError())
    with pytest.raises(UnknownEffect) as error:
        engine.execute(syscall, approval_id=approval)
    effect_id = str(error.value)
    storage.stop()

    restarted, restarted_kernel = restart(db)
    after = SyscallEngine(restarted, restarted_kernel)
    after.reconcile(effect_id, status=EffectStatus.STILL_UNKNOWN)
    assert restarted_kernel.get(process.process_id).status == ProcessStatus.WAITING
    with pytest.raises(EffectBlocked):
        after.execute(syscall)
    restarted.stop()


def test_unknown_effect_confirmed_applied_resumes_and_does_not_repeat(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    syscall = SyscallRequest(process.process_id, "test.effect", "scope", {"value": "x"})
    approval = engine.request_approval(syscall)
    engine.decide(approval, ApprovalDecision.APPROVED)
    engine.primitives["test.effect"] = lambda _: (_ for _ in ()).throw(TimeoutError())
    with pytest.raises(UnknownEffect) as error:
        engine.execute(syscall, approval_id=approval)
    effect_id = str(error.value)
    engine.reconcile(effect_id, status=EffectStatus.CONFIRMED_APPLIED, output={"value": "x"})
    assert kernel.get(process.process_id).status == ProcessStatus.RUNNING
    assert storage.write(lambda c: c.execute("SELECT COUNT(*) FROM effects WHERE process_id=?", (process.process_id,)).fetchone()[0]) == 1
    storage.stop()


def test_unknown_effect_confirmed_not_applied_keeps_history_and_allocates_new_effect(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    syscall = SyscallRequest(process.process_id, "test.effect", "scope", {"value": "x"})
    approval = engine.request_approval(syscall)
    engine.decide(approval, ApprovalDecision.APPROVED)
    engine.primitives["test.effect"] = lambda _: (_ for _ in ()).throw(TimeoutError())
    with pytest.raises(UnknownEffect) as error:
        engine.execute(syscall, approval_id=approval)
    old_effect_id = str(error.value)
    engine.reconcile(old_effect_id, status=EffectStatus.CONFIRMED_NOT_APPLIED)
    retry = engine.request_approval(syscall)
    engine.decide(retry, ApprovalDecision.APPROVED)
    engine.primitives["test.effect"] = lambda _: {"value": "x"}
    result = engine.execute(syscall, approval_id=retry)
    assert result.effect_id != old_effect_id
    assert storage.write(lambda c: c.execute("SELECT status FROM effects WHERE effect_id=?", (old_effect_id,)).fetchone()[0]) == EffectStatus.CONFIRMED_NOT_APPLIED
    storage.stop()


def test_secret_plaintext_is_absent_from_all_durable_and_api_projections(tmp_path: Path):
    secret = "closure-secret-plaintext"
    runtime = Runtime(tmp_path)
    app = create_app(runtime)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        headers = {"X-Vesper-Bootstrap": runtime.bootstrap_token}
        process_response = client.post("/api/processes", json={"origin": "test"}, headers=headers)
        assert process_response.status_code == 200, process_response.text
        process_id = process_response.json()["process"]["process_id"]
        waiting = client.post(f"/api/processes/{process_id}/syscalls", json={"operation": "test.effect", "target": "scope", "args": {"value": secret, "api_key": secret}}, headers=headers)
        assert secret not in waiting.text
        approval_id = waiting.json()["approval_id"]
        assert secret not in client.post(f"/api/approvals/{approval_id}", json={"decision": "APPROVED"}, headers=headers).text
        dumped = runtime.storage.write(lambda c: "\n".join(str(row[0]) for table, column in (("approvals", "args_json"), ("event_journal", "payload_json"), ("effects", "output_json")) for row in c.execute(f"SELECT COALESCE({column}, '') FROM {table}").fetchall()))
        assert secret not in dumped


def test_execution_pipeline_rejects_registered_exposed_and_precondition_bypasses(tmp_path: Path):
    storage, kernel = runtime(tmp_path)
    engine = SyscallEngine(storage, kernel)
    process = kernel.submit("test")
    engine.register("test.custom", "test", {"required": ["value"]}, "high", exposure="REGISTERED")
    engine.primitives["test.custom"] = lambda _: {"executed": True}
    request = SyscallRequest(process.process_id, "test.custom", "scope", {"value": "x"}, {"must_fail": True})
    with pytest.raises(NotRegistered):
        engine.execute(request)
    engine.register("test.custom", "test", {"required": ["value"]}, "high", exposure="EXPOSED")
    with pytest.raises(AuthorityDenied):
        engine.execute(request)
    storage.stop()
