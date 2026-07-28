from fastapi.testclient import TestClient

from vesper.api import Runtime, create_app
from vesper.candidate_review import CandidateReviewStore
from vesper.fallbacks import CandidateBuilder, FallbackRecord


def test_candidate_review_projection_is_readable(tmp_path):
    runtime = Runtime(tmp_path / "candidate.db")
    runtime.start()
    try:
        record = FallbackRecord("a", "research", ("analyze",), ("text",), ("text",), ("read",), ("quality",), ("read",))
        candidate = CandidateBuilder().build((record, record))
        runtime.candidate_reviews.submit(candidate, reviewer="director", evidence=("stable",))
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        response = client.get("/api/candidate-reviews")
        assert response.status_code == 200
        assert response.json()["reviews"][0]["decision"] == "PENDING"
        assert response.json()["reviews"][0]["activation_status"] == "PENDING_DIRECTOR_APPROVAL"
    finally:
        runtime.stop()


__all__ = ["CandidateReviewStore"]

