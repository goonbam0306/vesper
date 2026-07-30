from vesper.fallbacks import CandidateBuilder, FallbackRecord


def record(name: str, *, tool=("read",), evaluation=("quality",), permission=("read",), lane=None, recurrence=3, success=8, failure=1):
    return FallbackRecord(name, "research", ("retrieve", "analyze"), ("text",), ("report",), tool, evaluation, permission, success, failure, recurrence, existing_lane_id=lane)


def test_stable_cluster_recommends_skill_with_rich_evidence():
    candidate = CandidateBuilder().build((record("a"), record("b"), record("c")))
    assert candidate.recommended_abstraction == "SKILL"
    assert {name for name, _ in candidate.evidence} == {"structural", "semantic", "operational", "boundary", "reliability", "frequency", "combined"}


def test_existing_lane_with_context_skill_is_recommended():
    candidate = CandidateBuilder().build((record("research A", lane="lane.research"), record("investigate B", lane="lane.research"), record("research C", lane="lane.research")))
    assert candidate.recommended_abstraction == "EXISTING_LANE_WITH_SKILL"


def test_new_operational_boundary_recommends_new_lane():
    candidate = CandidateBuilder().build((record("a", tool=("read",)), record("b", tool=("browser",), permission=("network",)), record("c", tool=("browser",), permission=("network",))))
    assert candidate.recommended_abstraction == "NEW_LANE"


def test_weak_evidence_recommends_observation():
    candidate = CandidateBuilder().build((record("a", recurrence=0, success=0, failure=1), record("b", recurrence=0, success=0, failure=1)))
    assert candidate.recommended_abstraction == "INSUFFICIENT_EVIDENCE"


def test_structural_mismatch_is_rejected():
    try:
        CandidateBuilder().build((record("a"), record("b", evaluation=("latency",))))
        raise AssertionError("expected unstable cluster")
    except ValueError:
        pass


if __name__ == "__main__":
    test_stable_cluster_recommends_skill_with_rich_evidence()
    test_existing_lane_with_context_skill_is_recommended()
    test_new_operational_boundary_recommends_new_lane()
    test_weak_evidence_recommends_observation()
    test_structural_mismatch_is_rejected()


