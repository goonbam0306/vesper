from pathlib import Path

from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.syscalls import Decision, SyscallRequest


def auth(client: TestClient, request_id: str = "gate-f") -> dict[str, str]:
    return {
        "X-Vesper-Bootstrap": client.get("/api/bootstrap").json()["session"],
        "X-Client-Request-ID": request_id,
    }


def test_operational_surfaces_and_settings_are_safe_projections(tmp_path: Path):
    instance = Runtime(tmp_path)
    with TestClient(create_app(instance), base_url="http://127.0.0.1") as client:
        headers = auth(client)
        assert client.get("/api/processes").json() == {"processes": []}
        assert client.get("/api/approvals").json() == {"approvals": []}
        assert client.get("/api/connections").json()["connections"] == []

        initial = client.get("/api/settings").json()
        assert initial["model_route"]["status"] == "unconfigured"
        response = client.post(
            "/api/settings",
            headers=headers,
            json={"patch": {"director_display_name": "Director", "developer_diagnostics": True}},
        )
        assert response.status_code == 200
        saved = client.get("/api/settings").json()
        assert saved["director_display_name"] == "Director"
        assert saved["developer_diagnostics"] is True
    instance.stop()


def test_calendar_move_and_undo_create_new_revisions(tmp_path: Path):
    instance = Runtime(tmp_path)
    with TestClient(create_app(instance), base_url="http://127.0.0.1") as client:
        headers = auth(client, "calendar-create")
        created = client.post(
            "/api/calendar",
            headers=headers,
            json={"title": "Dogfood", "starts_at": "2026-07-24T10:00", "ends_at": "2026-07-24T11:00"},
        ).json()["calendar"]
        moved = client.patch(
            f"/api/calendar/{created['calendar_id']}",
            headers=auth(client, "calendar-move"),
            json={"patch": {"starts_at": "2026-07-24T12:00", "ends_at": "2026-07-24T13:00"}, "expected_revision": created["revision"]},
        ).json()["calendar"]
        assert moved["starts_at"] == "2026-07-24T12:00"
        assert moved["revision"] == created["revision"] + 1

        undone = client.post(
            f"/api/calendar/{created['calendar_id']}/undo",
            headers=auth(client, "calendar-undo"),
        ).json()["calendar"]
        assert undone["starts_at"] == "2026-07-24T10:00"
        assert undone["revision"] == moved["revision"] + 1
    instance.stop()


def test_authenticated_interaction_anchor_does_not_change_effective_authority(tmp_path: Path):
    instance = Runtime(tmp_path)
    with TestClient(create_app(instance), base_url="http://127.0.0.1") as client:
        headers = auth(client, "anchor-authority")
        target = "anchor-protected-resource"

        def count(table: str) -> int:
            return instance.storage.write(lambda c: c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        def effective_decision() -> str:
            return instance.storage.write(
                lambda c: instance.syscalls._decision(c, SyscallRequest("probe", "test.effect", target, {"value": "probe"}))[0].value
            )

        def denied_request(origin: str) -> None:
            process = client.post("/api/processes", headers=auth(client, f"{origin}-process"), json={"origin": origin})
            assert process.status_code == 200
            process_id = process.json()["process"]["process_id"]
            before_approvals, before_effects = count("approvals"), count("effects")
            response = client.post(
                f"/api/processes/{process_id}/syscalls",
                headers=auth(client, f"{origin}-syscall"),
                json={"operation": "test.effect", "target": target, "args": {"value": "must-remain-denied"}},
            )
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "AUTHORITY_DENIED"
            assert count("approvals") == before_approvals
            assert count("effects") == before_effects
            assert client.get(f"/api/processes/{process_id}").json()["process"]["status"] == "CREATED"

        # A selector-specific canonical rule makes the protected action DENY; no anchor participates in this rule.
        instance.syscalls.grant(
            operation="test.effect",
            resource_selector=target,
            decision=Decision.DENY,
            issuer="director",
            rule_id="anchor-authority-deny",
        )
        assert effective_decision() == "DENY"
        denied_request("anchor-absent")

        anchor_response = client.post(
            "/api/anchors",
            headers=headers,
            json={
                "anchor_type": "resource",
                "resource_ref": {"resource_type": "project", "resource_id": target},
                "selection_refs": [{"resource_type": "task", "resource_id": "selection-only"}],
                "view_scope_ref": "projects",
            },
        )
        assert anchor_response.status_code == 200
        anchor = anchor_response.json()["anchor"]
        assert anchor["authority"] == []
        assert anchor["resource_ref"]["resource_id"] == target
        assert anchor["selection_refs"][0]["resource_id"] == "selection-only"
        assert instance.storage.write(lambda c: c.execute("SELECT COUNT(*) FROM interaction_anchors WHERE anchor_id=?", (anchor["anchor_id"],)).fetchone()[0]) == 1

        assert effective_decision() == "DENY"
        denied_request("anchor-present")
    instance.stop()


def test_anchor_session_blocks_unauthenticated_mutation(tmp_path: Path):
    instance = Runtime(tmp_path)
    with TestClient(create_app(instance), base_url="http://127.0.0.1") as client:
        assert client.post("/api/projects", json={"name": "blocked"}).status_code == 401
    instance.stop()


def test_quick_idea_persists_without_provider_and_survives_reopen(tmp_path: Path):
    instance = Runtime(tmp_path)
    with TestClient(create_app(instance), base_url="http://127.0.0.1") as client:
        result = client.post(
            "/api/ideas",
            headers=auth(client),
            json={"payload": {"text": "offline provider must not block this"}},
        )
        assert result.status_code == 200
        assert client.get("/api/ideas").json()["ideas"][0]["payload"]["text"] == "offline provider must not block this"
    instance.stop()

    reopened = Runtime(tmp_path)
    reopened.start()
    assert reopened.core_apps.list_ideas()[0]["payload"]["text"] == "offline provider must not block this"
    reopened.stop()


def test_connection_projection_never_returns_secret_reference(tmp_path: Path):
    instance = Runtime(tmp_path)
    with TestClient(create_app(instance), base_url="http://127.0.0.1") as client:
        client.post(
            "/api/connections/secrets/metadata",
            headers=auth(client),
            json={"provider": "web", "label": "Primary", "secret_ref": "secret://opaque"},
        )
        projection = client.get("/api/connections").text
        assert "secret://opaque" not in projection
        assert "credential_ref" not in projection
    instance.stop()


def test_frontend_uses_system_api_not_browser_canonical_storage():
    source = (Path(__file__).parents[2] / "frontend" / "src" / "main.tsx").read_text()
    for forbidden in ("localStorage", "sessionStorage", "indexedDB", "sqlite", "credential_ref", "secret://"):
        assert forbidden not in source
    assert "X-Vesper-Bootstrap" in source
    assert "/api/bootstrap" in source
    assert "await load()" in source
    assert "Move rejected" in source
    assert "Compensating undo committed" in source
    assert "Persist first." in source
    assert "Exact structured decision required." in source
    assert "Credentials are never displayed here." in source
