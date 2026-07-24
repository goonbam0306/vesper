from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.core_apps import IdempotencyConflict, RevisionConflict


def runtime(tmp_path: Path) -> Runtime:
    instance = Runtime(tmp_path)
    instance.start()
    return instance


def test_core_resources_and_idea_are_distinct(tmp_path):
    instance = runtime(tmp_path)
    project = instance.core_apps.create_project("Vesper", "Ship the shell", "project-1")
    task = instance.core_apps.create_task("Build rail", project_id=project["project_id"], request_id="task-1")
    idea = instance.core_apps.capture_idea({"text": "Try a quieter home"}, "idea-1")
    assert project["resource_type"] == "project"
    assert task["resource_type"] == "task"
    assert idea["kind"] == "IDEA"
    assert "task_id" not in idea
    instance.stop()


def test_command_idempotency_and_revision_conflict(tmp_path):
    instance = runtime(tmp_path)
    first = instance.core_apps.create_project("Same", request_id="same")
    assert instance.core_apps.create_project("Same", request_id="same") == first
    with pytest.raises(IdempotencyConflict):
        instance.core_apps.create_project("Different", request_id="same")
    updated = instance.core_apps.update_project(first["project_id"], {"objective": "one"}, expected_revision=1, request_id="update")
    assert updated["revision"] == 2
    with pytest.raises(RevisionConflict):
        instance.core_apps.update_project(first["project_id"], {"objective": "stale"}, expected_revision=1, request_id="stale")
    instance.stop()


def test_anchor_has_no_authority(tmp_path):
    instance = runtime(tmp_path)
    anchor = instance.core_apps.create_anchor("project", "not-authorized")
    assert anchor["authority"] == []
    instance.stop()


def test_api_vertical_slice_survives_reopen(tmp_path):
    instance = Runtime(tmp_path)
    app = create_app(instance)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        token = client.get("/api/bootstrap").json()["session"]
        headers = {"X-Vesper-Bootstrap": token}
        project = client.post("/api/projects", json={"name": "Director work"}, headers=headers)
        assert project.status_code == 200
        task = client.post("/api/tasks", json={"title": "Capture acceptance test"}, headers=headers)
        assert task.status_code == 200
        idea = client.post("/api/ideas", json={"payload": {"text": "No provider needed"}}, headers=headers)
        assert idea.status_code == 200
        assert client.get("/api/projects").json()["projects"]
        assert client.get("/api/search?q=provider").json()["ideas"]
    instance.stop()
    reopened = Runtime(tmp_path)
    reopened.start()
    assert reopened.core_apps.list_projects()[0]["name"] == "Director work"
    assert reopened.core_apps.list_tasks()[0]["title"] == "Capture acceptance test"
    reopened.stop()


def test_frontend_does_not_use_direct_storage():
    source = Path(__file__).parents[2] / "frontend" / "src"
    forbidden = ("sqlite", "indexeddb", "localStorage", "sessionStorage")
    for path in source.rglob("*.ts*"):
        text = path.read_text()
        assert not any(token in text for token in forbidden), path
