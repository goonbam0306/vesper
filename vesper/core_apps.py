"""Kernel-owned stores for the Phase 4 core app vertical slices."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .storage import Storage


class CoreAppError(RuntimeError):
    code = "CORE_APP_ERROR"


class NotFound(CoreAppError):
    code = "NOT_FOUND"


class RevisionConflict(CoreAppError):
    code = "REVISION_CONFLICT"


class IdempotencyConflict(CoreAppError):
    code = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True)
class Resource:
    resource_id: str
    resource_type: str
    revision: int
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"resource_id": self.resource_id, "resource_type": self.resource_type, "revision": self.revision, **self.data}


class CoreApps:
    def __init__(self, storage: Storage):
        self.storage = storage

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _request_id(request_id: str | None) -> str:
        return request_id or str(uuid.uuid4())

    def _command(self, request_id: str | None, intent: dict[str, Any], operation):
        rid = self._request_id(request_id)
        encoded = json.dumps(intent, sort_keys=True, separators=(",", ":"))

        def write(c: sqlite3.Connection):
            existing = c.execute("SELECT command_json,result_json FROM command_requests WHERE client_request_id=?", (rid,)).fetchone()
            if existing:
                if existing["command_json"] != encoded:
                    raise IdempotencyConflict(rid)
                return json.loads(existing["result_json"])
            result = operation(c)
            c.execute("INSERT INTO command_requests(client_request_id,command_json,result_json) VALUES(?,?,?)", (rid, encoded, json.dumps(result, sort_keys=True)))
            return result

        return self.storage.write(write)

    def _resource(self, c: sqlite3.Connection, table: str, key: str, value: str, resource_type: str) -> dict[str, Any]:
        row = c.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
        if not row:
            raise NotFound(value)
        data = dict(row)
        rid = data.pop(key)
        result = Resource(rid, resource_type, int(data.pop("revision")), data).as_dict()
        result[key] = rid
        return result

    def create_project(self, name: str, objective: str = "", request_id: str | None = None) -> dict[str, Any]:
        project_id = str(uuid.uuid4())
        intent = {"op": "project.create", "name": name, "objective": objective}
        return self._command(request_id, intent, lambda c: self._insert_project(c, project_id, name, objective))

    def _insert_project(self, c, project_id, name, objective):
        c.execute("INSERT INTO projects(project_id,name,objective) VALUES(?,?,?)", (project_id, name, objective))
        return self._resource(c, "projects", "project_id", project_id, "project")

    def update_project(self, project_id: str, patch: dict[str, Any], expected_revision: int | None = None, request_id: str | None = None) -> dict[str, Any]:
        allowed = {key: patch[key] for key in ("name", "objective", "status") if key in patch}
        intent = {"op": "project.update", "project_id": project_id, "patch": allowed, "expected_revision": expected_revision}
        def update(c):
            row = c.execute("SELECT revision FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if not row:
                raise NotFound(project_id)
            if expected_revision is not None and row["revision"] != expected_revision:
                raise RevisionConflict(project_id)
            if not allowed:
                return self._resource(c, "projects", "project_id", project_id, "project")
            sets = ",".join(f"{key}=?" for key in allowed)
            c.execute(f"UPDATE projects SET {sets}, revision=revision+1, updated_at=? WHERE project_id=?", (*allowed.values(), self._now(), project_id))
            return self._resource(c, "projects", "project_id", project_id, "project")
        return self._command(request_id, intent, update)

    def list_projects(self) -> list[dict[str, Any]]:
        return self.storage.write(lambda c: [self._resource(c, "projects", "project_id", row["project_id"], "project") for row in c.execute("SELECT project_id FROM projects ORDER BY updated_at DESC")])

    def create_task(self, title: str, priority: int = 3, project_id: str | None = None, due_at: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        intent = {"op": "task.create", "title": title, "priority": priority, "project_id": project_id, "due_at": due_at}
        def create(c):
            if project_id and not c.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone():
                raise NotFound(project_id)
            c.execute("INSERT INTO tasks(task_id,title,priority,project_id,due_at) VALUES(?,?,?,?,?)", (task_id, title, priority, project_id, due_at))
            return self._resource(c, "tasks", "task_id", task_id, "task")
        return self._command(request_id, intent, create)

    def update_task(self, task_id: str, patch: dict[str, Any], expected_revision: int | None = None, request_id: str | None = None) -> dict[str, Any]:
        allowed = {key: patch[key] for key in ("title", "status", "priority", "project_id", "due_at") if key in patch}
        intent = {"op": "task.update", "task_id": task_id, "patch": allowed, "expected_revision": expected_revision}
        def update(c):
            row = c.execute("SELECT revision FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if not row:
                raise NotFound(task_id)
            if expected_revision is not None and row["revision"] != expected_revision:
                raise RevisionConflict(task_id)
            sets = ",".join(f"{key}=?" for key in allowed)
            if sets:
                c.execute(f"UPDATE tasks SET {sets}, revision=revision+1, updated_at=? WHERE task_id=?", (*allowed.values(), self._now(), task_id))
            return self._resource(c, "tasks", "task_id", task_id, "task")
        return self._command(request_id, intent, update)

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        def read(c):
            rows = c.execute("SELECT task_id FROM tasks WHERE (? IS NULL OR status=?) ORDER BY due_at IS NULL, due_at, priority", (status, status)).fetchall()
            return [self._resource(c, "tasks", "task_id", row["task_id"], "task") for row in rows]
        return self.storage.write(read)

    def create_calendar(self, title: str, starts_at: str, ends_at: str, project_id: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        calendar_id = str(uuid.uuid4())
        intent = {"op": "calendar.create", "title": title, "starts_at": starts_at, "ends_at": ends_at, "project_id": project_id}
        def create(c):
            if ends_at <= starts_at:
                raise CoreAppError("calendar end must be after start")
            c.execute("INSERT INTO calendar_items(calendar_id,title,starts_at,ends_at,project_id) VALUES(?,?,?,?,?)", (calendar_id, title, starts_at, ends_at, project_id))
            return self._resource(c, "calendar_items", "calendar_id", calendar_id, "calendar")
        return self._command(request_id, intent, create)

    def update_calendar(self, calendar_id: str, patch: dict[str, Any], expected_revision: int | None = None, request_id: str | None = None, *, record_undo: bool = True) -> dict[str, Any]:
        allowed = {key: patch[key] for key in ("title", "starts_at", "ends_at", "project_id") if key in patch}
        intent = {"op": "calendar.update", "calendar_id": calendar_id, "patch": allowed, "expected_revision": expected_revision}
        def update(c):
            row = c.execute("SELECT * FROM calendar_items WHERE calendar_id=?", (calendar_id,)).fetchone()
            if not row:
                raise NotFound(calendar_id)
            if expected_revision is not None and row["revision"] != expected_revision:
                raise RevisionConflict(calendar_id)
            starts = allowed.get("starts_at", row["starts_at"])
            ends = allowed.get("ends_at", row["ends_at"])
            if ends <= starts:
                raise CoreAppError("calendar end must be after start")
            if allowed:
                inverse = {key: row[key] for key in allowed}
                sets = ",".join(f"{key}=?" for key in allowed)
                c.execute(f"UPDATE calendar_items SET {sets}, revision=revision+1, updated_at=? WHERE calendar_id=?", (*allowed.values(), self._now(), calendar_id))
                updated = self._resource(c, "calendar_items", "calendar_id", calendar_id, "calendar")
                if record_undo:
                    c.execute(
                        "INSERT INTO committed_undo(undo_id,resource_type,resource_id,inverse_patch_json,source_revision) VALUES(?,?,?,?,?)",
                        (str(uuid.uuid4()), "calendar", calendar_id, json.dumps(inverse, sort_keys=True), updated["revision"]),
                    )
                return updated
            return self._resource(c, "calendar_items", "calendar_id", calendar_id, "calendar")
        return self._command(request_id, intent, update)

    def undo_calendar(self, calendar_id: str, request_id: str | None = None) -> dict[str, Any]:
        intent = {"op": "calendar.undo", "calendar_id": calendar_id}
        def undo(c):
            row = c.execute(
                "SELECT * FROM committed_undo WHERE resource_type='calendar' AND resource_id=? AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1",
                (calendar_id,),
            ).fetchone()
            if not row:
                raise NotFound(f"undo:{calendar_id}")
            current = c.execute("SELECT revision FROM calendar_items WHERE calendar_id=?", (calendar_id,)).fetchone()
            if not current:
                raise NotFound(calendar_id)
            if current["revision"] != row["source_revision"]:
                raise RevisionConflict(calendar_id)
            inverse = json.loads(row["inverse_patch_json"])
            sets = ",".join(f"{key}=?" for key in inverse)
            c.execute(f"UPDATE calendar_items SET {sets}, revision=revision+1, updated_at=? WHERE calendar_id=?", (*inverse.values(), self._now(), calendar_id))
            c.execute("UPDATE committed_undo SET consumed_at=? WHERE undo_id=?", (self._now(), row["undo_id"]))
            return self._resource(c, "calendar_items", "calendar_id", calendar_id, "calendar")
        return self._command(request_id, intent, undo)

    def list_ideas(self) -> list[dict[str, Any]]:
        def read(c):
            rows = c.execute("SELECT memory_id,kind,payload_json,revision,created_at,updated_at FROM memories WHERE kind='IDEA' ORDER BY created_at DESC").fetchall()
            return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]
        return self.storage.write(read)

    def settings(self) -> dict[str, Any]:
        def read(c):
            values = {row["setting_key"]: json.loads(row["value_json"]) for row in c.execute("SELECT setting_key,value_json FROM app_settings")}
            director = c.execute("SELECT preferred_name FROM director_profile WHERE id=1").fetchone()
            return {"director_display_name": director["preferred_name"] if director else None, **values}
        return self.storage.write(read)

    def update_settings(self, patch: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
        allowed = {key: patch[key] for key in ("director_display_name", "developer_diagnostics", "model_route", "first_boot_completed") if key in patch}
        intent = {"op": "settings.update", "patch": allowed}
        def update(c):
            if "director_display_name" in allowed:
                c.execute(
                    "INSERT INTO director_profile(id, preferred_name) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET preferred_name=excluded.preferred_name, updated_at=CURRENT_TIMESTAMP",
                    (allowed["director_display_name"],),
                )
            if "developer_diagnostics" in allowed:
                c.execute(
                    "INSERT INTO app_settings(setting_key,value_json,revision,updated_at) VALUES('developer_diagnostics',?,1,?) ON CONFLICT(setting_key) DO UPDATE SET value_json=excluded.value_json,revision=app_settings.revision+1,updated_at=excluded.updated_at",
                    (json.dumps(bool(allowed["developer_diagnostics"])), self._now()),
                )
            for key in ("model_route", "first_boot_completed"):
                if key in allowed:
                    c.execute(
                        "INSERT INTO app_settings(setting_key,value_json,revision,updated_at) VALUES(?,?,1,?) ON CONFLICT(setting_key) DO UPDATE SET value_json=excluded.value_json,revision=app_settings.revision+1,updated_at=excluded.updated_at",
                        (key, json.dumps(allowed[key], sort_keys=True), self._now()),
                    )
            values = {row["setting_key"]: json.loads(row["value_json"]) for row in c.execute("SELECT setting_key,value_json FROM app_settings")}
            director = c.execute("SELECT preferred_name FROM director_profile WHERE id=1").fetchone()
            return {"director_display_name": director["preferred_name"] if director else None, **values}
        return self._command(request_id, intent, update)


    def list_calendar(self) -> list[dict[str, Any]]:
        return self.storage.write(lambda c: [self._resource(c, "calendar_items", "calendar_id", row["calendar_id"], "calendar") for row in c.execute("SELECT calendar_id FROM calendar_items ORDER BY starts_at")])

    def capture_idea(self, payload: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
        """Commit Idea as Memory before any optional model organization."""
        intent = {"op": "idea.capture", "payload": payload}
        def capture(c):
            idea_id = str(uuid.uuid4())
            data = {"memory_id": idea_id, "kind": "IDEA", "schema_id": "idea", "schema_version": 1, "scope_refs": ["idea-inbox"], "payload": payload, "provenance": {"source": "quick_capture"}, "epistemic": "UNREVIEWED", "validity": "VALID"}
            now = self._now()
            c.execute("INSERT INTO memories(memory_id,kind,schema_id,schema_version,scope_refs_json,payload_json,provenance_json,epistemic,validity,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,1,?,?)", (idea_id, "IDEA", "idea", 1, json.dumps(["idea-inbox"]), json.dumps(payload, sort_keys=True), json.dumps(data["provenance"]), "UNREVIEWED", "VALID", now, now))
            return data | {"revision": 1, "created_at": now, "updated_at": now}
        return self._command(request_id, intent, capture)

    def create_anchor(self, anchor_type: str, resource_ref: dict[str, Any], selection_refs: list[dict[str, Any]] | None = None, view_scope_ref: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        anchor_id = str(uuid.uuid4())
        selection_refs = selection_refs or []
        intent = {"op": "anchor.create", "anchor_type": anchor_type, "resource_ref": resource_ref, "selection_refs": selection_refs, "view_scope_ref": view_scope_ref}
        def create(c):
            resource_type = str(resource_ref.get("resource_type", "reference"))
            resource_id = str(resource_ref.get("resource_id", ""))
            c.execute("INSERT INTO interaction_anchors(anchor_id,resource_type,resource_id) VALUES(?,?,?)", (anchor_id, resource_type, resource_id))
            return {"anchor_id": anchor_id, "anchor_type": anchor_type, "resource_ref": resource_ref, "selection_refs": selection_refs, "view_scope_ref": view_scope_ref, "authority": []}
        return self._command(request_id, intent, create)

    def search(self, query: str) -> dict[str, Any]:
        term = f"%{query.lower()}%"
        def read(c):
            projects = [self._resource(c, "projects", "project_id", row["project_id"], "project") for row in c.execute("SELECT project_id FROM projects WHERE lower(name) LIKE ? OR lower(objective) LIKE ?", (term, term))]
            tasks = [self._resource(c, "tasks", "task_id", row["task_id"], "task") for row in c.execute("SELECT task_id FROM tasks WHERE lower(title) LIKE ?", (term,))]
            ideas = [dict(row) for row in c.execute("SELECT memory_id,kind,payload_json,revision FROM memories WHERE kind='IDEA' AND lower(payload_json) LIKE ? ORDER BY updated_at DESC", (term,))]
            return {"projects": projects, "tasks": tasks, "ideas": ideas}
        return self.storage.write(read)
