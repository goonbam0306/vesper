from vesper.model_escalation import FailureClass, ModelEscalator


def test_same_lane_escalates_to_stronger_eligible_route_with_budget():
    escalator = ModelEscalator()
    result = escalator.select(
        lane_id="code",
        lane_version=1,
        required_capabilities=frozenset({"text"}),
        routes=(
            {"route_id": "weak", "capabilities": {"text"}, "reliability": 0.8, "rank": 1},
            {"route_id": "strong", "capabilities": {"text"}, "reliability": 0.95, "rank": 2},
        ),
        failure=FailureClass.STRUCTURED_OUTPUT_INVALID,
        prior_route_id="weak",
        attempt_count=1,
        max_attempts=2,
    )
    assert result.route_id == "strong"
    assert (result.lane_id, result.lane_version) == ("code", 1)


def test_route_cycle_is_bounded_and_failure_is_classified():
    escalator = ModelEscalator()
    assert escalator.classify("context overflow") is FailureClass.CONTEXT_OVERFLOW
    assert escalator.select("code", 1, frozenset({"text"}), ({"route_id": "weak", "capabilities": {"text"}, "reliability": .8, "rank": 1},), FailureClass.PROVIDER_UNAVAILABLE, "weak", 2, 2) is None
