from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.kernel import (
    AuthorityViolation,
    DependencyCycle,
    InvalidTransition,
    Kernel,
    ProcessStatus,
    WaitReason,
)


def runtime(tmp_path: Path) -> Runtime:
    return Runtime(tmp_path)


def count(rt: Runtime, table: str) -> int:
    return rt.storage.write(lambda conn: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_volatile_completion_creates_no_durable_lifecycle_rows(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        process = rt.kernel.submit("disposable", volatile=True)
        rt.kernel.transition(process.process_id, ProcessStatus.RUNNING)
        completed = rt.kernel.transition(process.process_id, ProcessStatus.COMPLETED)
        assert completed.volatile is True
        assert count(rt, "processes") == 0
        assert count(rt, "event_journal") == 0
    finally:
        rt.stop()


def test_promotion_same_id_is_atomic_and_idempotent(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        process = rt.kernel.submit("disposable", volatile=True)
        promoted = rt.kernel.promote(process.process_id, boundary="canonical_state")
        again = rt.kernel.promote(process.process_id, boundary="canonical_state")
        assert promoted.process_id == process.process_id == again.process_id
        assert promoted.volatile is False
        assert count(rt, "processes") == 1
        assert count(rt, "event_journal") == 1
    finally:
        rt.stop()


def test_promotion_failure_leaves_no_partial_durable_state(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        process = rt.kernel.submit("disposable", volatile=True)
        with pytest.raises(RuntimeError):
            rt.kernel.promote(process.process_id, boundary="canonical_state", fault_after_event=True)
        assert count(rt, "processes") == 0
        assert count(rt, "event_journal") == 0
        assert rt.kernel.get(process.process_id).volatile is True
    finally:
        rt.stop()


def test_waiting_recovery_requires_matching_wake_event(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        process = rt.kernel.submit("director")
        rt.kernel.transition(process.process_id, ProcessStatus.RUNNING)
        waiting = rt.kernel.wait(process.process_id, WaitReason.USER_INPUT, wake_key="reply-1")
        assert waiting.status == ProcessStatus.WAITING
    finally:
        rt.stop()

    restarted = runtime(tmp_path)
    restarted.start()
    try:
        assert restarted.kernel.get(process.process_id).status == ProcessStatus.WAITING
        assert restarted.kernel.wake("wrong-key") == []
        assert restarted.kernel.get(process.process_id).status == ProcessStatus.WAITING
        resumed = restarted.kernel.wake("reply-1")
        assert [item.process_id for item in resumed] == [process.process_id]
        assert restarted.kernel.get(process.process_id).status == ProcessStatus.RUNNING
    finally:
        restarted.stop()


def test_terminal_process_cannot_resume(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        process = rt.kernel.submit("director")
        rt.kernel.transition(process.process_id, ProcessStatus.RUNNING)
        rt.kernel.transition(process.process_id, ProcessStatus.COMPLETED)
        with pytest.raises(InvalidTransition):
            rt.kernel.transition(process.process_id, ProcessStatus.RUNNING)
    finally:
        rt.stop()


def test_child_authority_is_attenuated_and_lineage_is_durable(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        parent = rt.kernel.submit("director", authority={"read", "write"}, delegable_authority={"read"})
        with pytest.raises(AuthorityViolation):
            rt.kernel.spawn(parent.process_id, authority={"write"})
        child = rt.kernel.spawn(parent.process_id, authority={"read"}, delegation_package={"task": "inspect"})
        persisted = rt.kernel.get(child.process_id)
        assert persisted.parent_process_id == parent.process_id
        assert persisted.authority == ("read",)
    finally:
        rt.stop()


def test_dependency_cycle_rejected_and_unmet_dependency_blocks_execution(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        first = rt.kernel.submit("director")
        second = rt.kernel.submit("director")
        rt.kernel.add_dependency(second.process_id, first.process_id)
        with pytest.raises(InvalidTransition):
            rt.kernel.transition(second.process_id, ProcessStatus.RUNNING)
        with pytest.raises(DependencyCycle):
            rt.kernel.add_dependency(first.process_id, second.process_id)
        rt.kernel.transition(first.process_id, ProcessStatus.RUNNING)
        rt.kernel.transition(first.process_id, ProcessStatus.COMPLETED)
        assert rt.kernel.transition(second.process_id, ProcessStatus.RUNNING).status == ProcessStatus.RUNNING
    finally:
        rt.stop()


def test_watch_snapshot_cursor_resume_and_expiry_are_typed(tmp_path: Path):
    rt = runtime(tmp_path)
    with TestClient(create_app(rt)) as client:
        headers = {"host": "127.0.0.1", "x-vesper-bootstrap": rt.bootstrap_token}
        snapshot = client.get("/api/snapshot", headers={"host": "127.0.0.1"}).json()
        cursor = snapshot["cursor"]
        response = client.post("/api/processes", headers={**headers, "x-client-request-id": "watch-1"}, json={"origin": "director"})
        assert response.status_code == 200
        watch = client.get(f"/api/watch?cursor={cursor}", headers={"host": "127.0.0.1"}).json()
        assert watch["ok"] is True
        assert watch["events"]
        assert [event["sequence"] for event in watch["events"]] == sorted(event["sequence"] for event in watch["events"])
        expired = client.get("/api/watch?cursor=-1", headers={"host": "127.0.0.1"})
        assert expired.status_code == 410
        assert expired.json()["error"]["code"] == "CURSOR_EXPIRED"


def test_command_idempotency_atomic_state_event_and_query_no_process(tmp_path: Path):
    rt = runtime(tmp_path)
    with TestClient(create_app(rt)) as client:
        headers = {"host": "127.0.0.1", "x-vesper-bootstrap": rt.bootstrap_token}
        assert client.get("/api/snapshot", headers={"host": "127.0.0.1"}).json()["processes"] == []
        first = client.post("/api/processes", headers={**headers, "x-client-request-id": "same"}, json={"origin": "director"}).json()
        again = client.post("/api/processes", headers={**headers, "x-client-request-id": "same"}, json={"origin": "director"}).json()
        assert first["result"]["process_id"] == again["result"]["process_id"]
        assert count(rt, "processes") == 1
        assert count(rt, "event_journal") == 1
        failed = rt.kernel.submit("director")
        with pytest.raises(RuntimeError):
            rt.kernel.transition(failed.process_id, ProcessStatus.RUNNING, fault_after_event=True)
        assert rt.kernel.get(failed.process_id).status == ProcessStatus.CREATED


def test_scheduler_prioritizes_interactive_under_background_load(tmp_path: Path):
    rt = runtime(tmp_path)
    rt.start()
    try:
        for index in range(40):
            rt.kernel.submit(f"background-{index}", priority="BACKGROUND")
        interactive = rt.kernel.submit("director", priority="INTERACTIVE")
        slices = rt.kernel.run_scheduler(max_slices=1)
        assert slices[0].process_id == interactive.process_id
        metrics = rt.kernel.scheduler_metrics()
        assert metrics["background_queue_depth"] >= 1
        assert metrics["interactive_starved"] is False
    finally:
        rt.stop()
