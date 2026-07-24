from pathlib import Path

import pytest

from vesper.kernel import ProcessStatus
from vesper.syscalls import (
    ApprovalDecision,
    ApprovalMismatch,
    ApprovalRequired,
    AuthorityDenied,
    Decision,
    SyscallRequest,
    SyscallEngine,
    UnknownEffect,
)
from vesper.storage import Storage
from vesper.kernel import Kernel


def runtime(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate()
    storage.start()
    kernel = Kernel(storage)
    engine = SyscallEngine(storage, kernel)
    return storage, kernel, engine


def test_visible_without_approval_enters_approval_gate(tmp_path: Path):
    storage, kernel, engine = runtime(tmp_path)
    process = kernel.submit("test")
    with pytest.raises(ApprovalRequired):
        engine.execute(SyscallRequest(process.process_id, "test.effect", "secret", {"value": "x"}))
    storage.stop()


def test_allow_executes_output_without_effect(tmp_path: Path):
    storage, kernel, engine = runtime(tmp_path)
    process = kernel.submit("test")
    result = engine.execute(SyscallRequest(process.process_id, "test.echo", "*", {"message": "hello"}))
    assert result.output == {"message": "hello"}
    assert result.effect_id is None
    storage.stop()


def test_approval_is_exact_and_one_shot(tmp_path: Path):
    storage, kernel, engine = runtime(tmp_path)
    process = kernel.submit("test")
    request = SyscallRequest(process.process_id, "test.effect", "target-a", {"value": "x"})
    with pytest.raises(ApprovalRequired):
        engine.execute(request)
    approval_id = engine.request_approval(request)
    assert kernel.get(process.process_id).status == ProcessStatus.WAITING
    engine.decide(approval_id, ApprovalDecision.APPROVED)
    with pytest.raises(ApprovalMismatch):
        engine.execute(SyscallRequest(process.process_id, "test.effect", "target-b", {"value": "x"}), approval_id=approval_id)
    result = engine.execute(request, approval_id=approval_id)
    assert result.effect_id
    with pytest.raises(ApprovalMismatch):
        engine.execute(request, approval_id=approval_id)
    storage.stop()


def test_edit_creates_new_identity(tmp_path: Path):
    storage, kernel, engine = runtime(tmp_path)
    process = kernel.submit("test")
    original = SyscallRequest(process.process_id, "test.effect", "a", {"value": "1"})
    edited = SyscallRequest(process.process_id, "test.effect", "b", {"value": "2"})
    old_id = engine.request_approval(original)
    new_id = engine.decide(old_id, ApprovalDecision.EDITED, edited=edited)
    assert new_id != old_id
    with pytest.raises(ApprovalMismatch):
        engine.execute(original, approval_id=old_id)
    storage.stop()


def test_denial_cannot_be_softened_and_unknown_effect_is_reconciliation_gate(tmp_path: Path):
    storage, kernel, engine = runtime(tmp_path)
    process = kernel.submit("test")
    engine.grant(operation="test.effect", resource_selector="blocked", decision=Decision.DENY)
    request = SyscallRequest(process.process_id, "test.effect", "blocked", {"value": "x"})
    with pytest.raises(AuthorityDenied):
        engine.execute(request)
    engine.primitives["test.effect"] = lambda _: (_ for _ in ()).throw(TimeoutError())
    approval = engine.request_approval(SyscallRequest(process.process_id, "test.effect", "allowed", {"value": "x"}))
    engine.decide(approval, ApprovalDecision.APPROVED)
    with pytest.raises(UnknownEffect) as error:
        engine.execute(SyscallRequest(process.process_id, "test.effect", "allowed", {"value": "x"}), approval_id=approval)
    engine.reconcile(str(error.value), status=__import__("vesper.syscalls", fromlist=["EffectStatus"]).EffectStatus.RECONCILED)
    storage.stop()
####Tool(namespace=