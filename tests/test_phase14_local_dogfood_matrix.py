from pathlib import Path

from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.approved_file_apply import ApprovedFileApply, FileApplyApproval, PatchOperation, PatchSet
from vesper.composition import Composer
from vesper.execution_graph import ExecutionGraphStore, GraphNodeType
from vesper.fallbacks import CandidateBuilder, FallbackRecord
from vesper.process_policy import ProcessPolicy, ProcessPolicyStore, ProcessRecurrenceStore
from vesper.verification import VerificationRunner


def auth(client: TestClient, request_id: str) -> dict[str, str]:
    return {
        "X-Vesper-Bootstrap": client.get("/api/bootstrap").json()["session"],
        "X-Client-Request-ID": request_id,
    }


def test_phase14_local_dogfood_matrix(tmp_path: Path):
    runtime = Runtime(tmp_path)
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        # daily briefing / project / task management
        headers = auth(client, "daily-briefing")
        assert client.get("/api/dashboard/today").status_code == 200
        project = client.post("/api/projects", headers=headers, json={"name": "Dogfood"}).json()["project"]
        task = client.post(
            "/api/tasks", headers=auth(client, "task-create"),
            json={"title": "Research local contract", "project_id": project["project_id"]},
        )
        assert task.status_code == 200
        assert client.get("/api/projects").json()["projects"]

        # calendar operation with revision and undo
        created = client.post(
            "/api/calendar", headers=auth(client, "calendar-create"),
            json={"title": "Dogfood calendar", "starts_at": "2026-07-24T10:00", "ends_at": "2026-07-24T11:00"},
        ).json()["calendar"]
        moved = client.patch(
            f"/api/calendar/{created['calendar_id']}", headers=auth(client, "calendar-move"),
            json={"patch": {"starts_at": "2026-07-24T12:00", "ends_at": "2026-07-24T13:00"}, "expected_revision": created["revision"]},
        ).json()["calendar"]
        assert client.post(f"/api/calendar/{created['calendar_id']}/undo", headers=auth(client, "calendar-undo")).json()["calendar"]["revision"] == moved["revision"] + 1

        # memory recall and offline degradation
        client.post("/api/ideas", headers=auth(client, "memory-write"), json={"payload": {"text": "offline recall fixture"}})
        assert "offline recall fixture" in client.get("/api/ideas").text
        assert client.get("/api/connections").status_code == 200

        # coding/document generation: bounded apply -> verification -> composition
        target = tmp_path / "dogfood.txt"
        target.write_text("before\n", encoding="utf-8")
        patch = PatchSet("phase14-dogfood", tmp_path, (PatchOperation("dogfood.txt", "before\n", "after\n"),))
        applied = ApprovedFileApply(tmp_path).apply(patch, approval=FileApplyApproval("director-phase14", "director", patch.patch_id, tmp_path))
        report = VerificationRunner().run(patch.patch_id, ("content",), {"content": {"source": "kernel", "status": "passed", "exit_code": 0, "command": "content-check"}})
        document = Composer().compose(report, title="Phase 14 dogfood", body="bounded result")
        assert applied.changed_paths == ("dogfood.txt",)
        assert document.sources == (patch.patch_id,)

        # failure diagnosis/retry and restart recovery
        process = client.post("/api/processes", headers=auth(client, "phase14-process"), json={"origin": "phase14-dogfood"}).json()["process"]
        process_id = process["process_id"]
        graph = ExecutionGraphStore(runtime.storage)
        graph_id = graph.create_graph(process_id=process_id).graph_id
        node_id = "phase14-node"
        graph.add_node(graph_id, node_id=node_id, node_type=GraphNodeType.DETERMINISTIC_OPERATION, operation_name="pytest", max_attempts=2)
        graph.start_node(graph_id, node_id)
        graph.fail_node(graph_id, node_id)
        assert graph.retry_node(graph_id, node_id, reason="provider unavailable") is True
        graph.start_node(graph_id, node_id)
        assert graph.is_stalled(graph_id, node_id, failure_reason="provider unavailable", threshold=2) is True
        graph.recover_running_nodes(graph_id)

        # recurring process remains local and durable
        recurrence = ProcessRecurrenceStore(runtime.storage)
        recurrence.configure(process_id, interval_seconds=60, max_runs=2)
        assert recurrence.next_run(process_id, now="2026-07-28T00:00:00+00:00") == 1

        # approval-gated action and Lane candidate proposal
        policy = ProcessPolicyStore(runtime.storage).create(
            ProcessPolicy(process_id=process_id, approval_boundaries=("external_write",))
        )
        assert policy.requires_approval("external_write") is True
        record = FallbackRecord("fallback-a", "research", ("retrieve",), ("text",), ("document",), ("local",), ("quality",), ("read",))
        candidate = CandidateBuilder().build((record, record))
        assert candidate.activation_status == "PENDING_DIRECTOR_APPROVAL"

    runtime.stop()