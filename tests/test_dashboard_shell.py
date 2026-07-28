import pytest
from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


@pytest.fixture
def runtime(tmp_path):
    return Runtime(tmp_path)


def test_dashboard_shell_returns_operational_sections(runtime):
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        response = client.get("/api/dashboard/today", headers={"X-Vesper-Bootstrap": runtime.bootstrap_token})
    assert response.status_code == 200
    body = response.json()
    assert set(("processes", "lanes", "approvals", "effects", "memory")).issubset(body)