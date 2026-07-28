from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app


def test_lane_dashboard_shell_exposes_management_surface(tmp_path):
    runtime = Runtime(tmp_path / "lane-dashboard.db")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        response = client.get("/dashboard/lanes")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Lane Management" in response.text
    assert 'aria-label=\'Lane registry\'' in response.text
    assert "Candidate reviews" in response.text
    assert "/api/lanes" in response.text
    assert "/api/candidate-reviews" in response.text
    assert "refresh-lanes" in response.text
    assert "lane-detail" in response.text
    assert "inspectLane" in response.text
    assert "laneAction" in response.text
    assert "enable-lane" in response.text
    assert "disable-lane" in response.text
    assert "retire-lane" in response.text
    assert "supersede-lane" in response.text
    assert "/contract`" in response.text
    assert "/history`" in response.text
    assert "X-Vesper-Bootstrap" in response.text


__all__ = []

