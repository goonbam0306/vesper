from vesper.fallbacks import CandidateBuilder, FallbackRecord


def record(name: str, *, tool=("read",), evaluation=("quality",), permission=("read",)):
    return FallbackRecord(name, "research", ("retrieve", "analyze"), ("text",), ("report",), tool, evaluation, permission)


def test_repeated_stable_cluster_defaults_to_skill_without_explicit_lane_contract():
    candidate = CandidateBuilder().build((record("a"), record("b"), record("c")))
    assert candidate.recommended_abstraction == "SKILL"
    assert candidate.recommendation_reason == "reusable cognitive pattern"
    assert candidate.recommendation_reason


def test_small_or_operationally_mixed_cluster_recommends_skill():
    candidate = CandidateBuilder().build((record("a"), record("b", tool=("read", "write"))))
    assert candidate.recommended_abstraction == "SKILL"
    assert candidate.recommendation_reason


def test_structural_mismatch_is_rejected():
    try:
        CandidateBuilder().build((record("a"), record("b", evaluation=("latency",))))
        raise AssertionError("expected unstable cluster")
    except ValueError:
        pass


if __name__ == "__main__":
    test_repeated_stable_cluster_defaults_to_skill_without_explicit_lane_contract()
    test_small_or_operationally_mixed_cluster_recommends_skill()
    test_structural_mismatch_is_rejected()


