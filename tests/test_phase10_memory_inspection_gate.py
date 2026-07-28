from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def test_memory_listing_exposes_latest_provenance_without_secrets(tmp_path):
    runtime = Runtime(tmp_path / "memory-ui.db")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"host": "127.0.0.1", "x-vesper-bootstrap": runtime.bootstrap_token}
        created = client.post(
            "/api/memories",
            headers=headers,
            json={
                "kind": "idea",
                "payload": {"text": "inspectable idea"},
                "provenance": {"source": "director", "work_unit": "capture"},
            },
        )
        assert created.status_code == 200
        response = client.get("/api/memories", headers=headers)
        assert response.status_code == 200
        memories = response.json()["memories"]
        item = next(item for item in memories if item["memory_id"] == created.json()["memory"]["memory_id"])
        assert item["provenance"]["source"] == "director"
        assert item["payload"]["text"] == "inspectable idea"
        assert "credential" not in response.text.lower()
        assert "secret" not in response.text.lower()
        assert "token" not in response.text.lower()


__all__ = []
