from __future__ import annotations

from pathlib import Path

import pytest

from vesper.api import Runtime
from vesper.lanes import LaneDefinition
from vesper.model_runtime import ModelRoute, ProviderResponse
from vesper.routing_proposals import (
    MainLLMRouter,
    MainLLMRouteResult,
    RoutingDispatcher,
    RoutingDispatchProcessNotFoundError,
    RoutingOutputMalformedError,
    RoutingDisposition,
    RoutingFallbackInvalidError,
    RoutingGraphInvalidError,
    RoutingLaneDisabledError,
    RoutingLaneNotFoundError,
    RoutingProposal,
    RoutingProposalError,
    RoutingProposalValidator,
)


def make_lane(lane_id: str = "explore", version: int = 1, enabled: bool = True) -> LaneDefinition:
    return LaneDefinition(
        lane_id=lane_id, version=version, name="Explore",
        purpose="Explore a bounded question", input_schema={}, output_schema={}, enabled=enabled,
    )


def runtime(tmp_path: Path) -> Runtime:
    instance = Runtime(tmp_path)
    instance.start()
    return instance


def test_main_llm_router_returns_validated_direct_proposal(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("routing-test")
        route = ModelRoute("routing-test", "fake", "fake", frozenset({"text"}), "local", .9, 0.0, 1.0, True, None)
        instance.providers.register("fake", lambda _route, _pack: ProviderResponse(
            '{"disposition":"DIRECT","required_capabilities":[],"requested_context":[],"confidence":0.92,"rationale_summary":"No specialized execution required."}'
        ))
        router = MainLLMRouter(instance.cognitive, instance.lanes)
        result = router.route(process.process_id, "Explain this simply.", route=route)
        assert result.validated.proposal.disposition is RoutingDisposition.DIRECT
        assert result.validated.resolved_lane_id is None
        assert result.validated.resolved_lane_version is None
    finally:
        instance.stop()


def test_main_llm_router_resolves_lane_without_creating_invocation(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("routing-test")
        instance.lanes.register(make_lane(version=1))
        instance.lanes.register(make_lane(version=2))
        route = ModelRoute("routing-test", "fake", "fake", frozenset({"text"}), "local", .9, 0.0, 1.0, True, None)
        instance.providers.register("fake", lambda _route, _pack: ProviderResponse(
            '{"disposition":"LANE","lane_id":"explore","required_capabilities":[],"requested_context":[]}'
        ))
        before = instance.lane_invocations.list(process.process_id)
        result = MainLLMRouter(instance.cognitive, instance.lanes).route(process.process_id, "Analyze this.", route=route)
        assert (result.validated.resolved_lane_id, result.validated.resolved_lane_version) == ("explore", 2)
        assert instance.lane_invocations.list(process.process_id) == before
    finally:
        instance.stop()


def test_direct_proposal_validates_without_execution_target(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        result = RoutingProposalValidator(instance.lanes).validate(
            RoutingProposal(disposition=RoutingDisposition.DIRECT)
        )
        assert result.proposal.disposition is RoutingDisposition.DIRECT
        assert result.resolved_lane_id is None
        assert result.resolved_lane_version is None
    finally:
        instance.stop()


def test_lane_proposal_resolves_exact_enabled_latest_version(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        instance.lanes.register(make_lane(version=1))
        instance.lanes.register(make_lane(version=2))
        result = RoutingProposalValidator(instance.lanes).validate(
            RoutingProposal(disposition=RoutingDisposition.LANE, lane_id="explore")
        )
        assert (result.resolved_lane_id, result.resolved_lane_version) == ("explore", 2)
    finally:
        instance.stop()


def test_unknown_disposition_is_rejected(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        with pytest.raises(RoutingProposalError) as exc_info:
            RoutingProposalValidator(instance.lanes).validate(
                RoutingProposal(disposition="UNKNOWN")
            )
        assert exc_info.value.code == "ROUTING_DISPOSITION_INVALID"
    finally:
        instance.stop()


def test_explicit_lane_version_is_resolved_and_must_be_enabled(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        instance.lanes.register(make_lane(version=1))
        instance.lanes.register(make_lane(version=2))
        validator = RoutingProposalValidator(instance.lanes)
        result = validator.validate(RoutingProposal(
            disposition=RoutingDisposition.LANE, lane_id="explore", lane_version=1
        ))
        assert (result.resolved_lane_id, result.resolved_lane_version) == ("explore", 1)
        instance.lanes.set_enabled("explore", 1, False)
        with pytest.raises(RoutingLaneDisabledError):
            validator.validate(RoutingProposal(
                disposition=RoutingDisposition.LANE, lane_id="explore", lane_version=1
            ))
    finally:
        instance.stop()


def test_missing_lane_is_rejected(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        with pytest.raises(RoutingLaneNotFoundError):
            RoutingProposalValidator(instance.lanes).validate(
                RoutingProposal(disposition=RoutingDisposition.LANE, lane_id="missing")
            )
    finally:
        instance.stop()


def test_fallback_requires_bounded_inferred_function_and_does_not_mutate_registry(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        before = instance.lanes.list()
        validator = RoutingProposalValidator(instance.lanes)
        result = validator.validate(RoutingProposal(
            disposition=RoutingDisposition.FALLBACK, inferred_function="game_balance_analysis"
        ))
        assert result.proposal.inferred_function == "game_balance_analysis"
        assert instance.lanes.list() == before
        with pytest.raises(RoutingFallbackInvalidError):
            validator.validate(RoutingProposal(disposition=RoutingDisposition.FALLBACK))
    finally:
        instance.stop()


def test_graph_validation_rejects_invalid_shape_without_side_effects(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        before = instance.lanes.list()
        with pytest.raises(RoutingGraphInvalidError):
            RoutingProposalValidator(instance.lanes).validate(
                RoutingProposal(disposition=RoutingDisposition.GRAPH, graph_proposal="future")
            )
        assert instance.lanes.list() == before
    finally:
        instance.stop()


def test_graph_rejects_top_level_direct_as_node_type(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        with pytest.raises(RoutingGraphInvalidError):
            RoutingProposalValidator(instance.lanes).validate(
                RoutingProposal(disposition=RoutingDisposition.GRAPH, graph_proposal={
                    "nodes": [{"node_id": "direct", "type": "DIRECT"}]
                })
            )
    finally:
        instance.stop()


def test_graph_validates_unique_nodes_dependencies_and_enabled_lane(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        instance.lanes.register(make_lane())
        graph = {"nodes": [
            {"node_id": "a", "type": "LANE", "lane_id": "explore"},
            {"node_id": "b", "type": "LANE", "lane_id": "explore", "dependencies": ["a"]},
        ]}
        result = RoutingProposalValidator(instance.lanes).validate(
            RoutingProposal(disposition=RoutingDisposition.GRAPH, graph_proposal=graph)
        )
        assert result.resolved_lane_id is None
        with pytest.raises(RoutingGraphInvalidError):
            RoutingProposalValidator(instance.lanes).validate(
                RoutingProposal(disposition=RoutingDisposition.GRAPH, graph_proposal={"nodes": [
                    {"node_id": "a", "type": "LANE", "lane_id": "explore"},
                    {"node_id": "a", "type": "LANE", "lane_id": "explore"},
                ]})
            )
    finally:
        instance.stop()


@pytest.mark.parametrize("output", ["not json", "{}", '{"disposition":"UNKNOWN"}', '{"disposition":"LANE"}'])
def test_main_llm_router_rejects_malformed_or_invalid_output(tmp_path: Path, output: str):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("routing-test")
        route = ModelRoute("routing-test", "fake", "fake", frozenset({"text"}), "local", .9, 0.0, 1.0, True, None)
        instance.providers.register("fake", lambda _route, _pack: ProviderResponse(output))
        with pytest.raises((RoutingOutputMalformedError, RoutingProposalError, RoutingLaneNotFoundError)):
            MainLLMRouter(instance.cognitive, instance.lanes).route(process.process_id, "Request.", route=route)
    finally:
        instance.stop()


def test_main_llm_router_validates_minimal_graph_without_execution(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("routing-test")
        instance.lanes.register(make_lane())
        route = ModelRoute("routing-test", "fake", "fake", frozenset({"text"}), "local", .9, 0.0, 1.0, True, None)
        instance.providers.register("fake", lambda _route, _pack: ProviderResponse(
            '{"disposition":"GRAPH","graph_proposal":{"nodes":[{"node_id":"a","type":"LANE","lane_id":"explore"},{"node_id":"b","type":"LANE","lane_id":"explore","dependencies":["a"]}]},"required_capabilities":[],"requested_context":[]}'
        ))
        result = MainLLMRouter(instance.cognitive, instance.lanes).route(process.process_id, "Do both.", route=route)
        assert result.validated.proposal.disposition is RoutingDisposition.GRAPH
        assert instance.lane_invocations.list(process.process_id) == []
    finally:
        instance.stop()


def test_router_prompt_contract_exposes_enabled_lanes_and_graph_boundary(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        instance.lanes.register(make_lane(enabled=True))
        instance.lanes.register(make_lane(lane_id="disabled", enabled=False))
        contract = MainLLMRouter(instance.cognitive, instance.lanes).build_routing_contract("Request.")
        assert set(contract["routing_contract"]["dispositions"]) == {"DIRECT", "LANE", "GRAPH", "FALLBACK"}
        assert contract["routing_contract"]["graph_node_types"] == ["LANE"]
        assert [lane["lane_id"] for lane in contract["available_lanes"]] == ["explore"]
    finally:
        instance.stop()


def test_routing_dispatch_creates_exact_validated_lane_invocation(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("dispatch-test")
        instance.lanes.register(make_lane(lane_id="diagnose", version=1, enabled=False))
        instance.lanes.register(make_lane(lane_id="diagnose", version=2, enabled=True))
        proposal = RoutingProposal(RoutingDisposition.LANE, lane_id="diagnose")
        validated = RoutingProposalValidator(instance.lanes).validate(proposal)
        route_result = MainLLMRouteResult(proposal, validated, "attempt-1", "route-1")
        instance.lanes.register(make_lane(lane_id="diagnose", version=3, enabled=True))
        result = RoutingDispatcher(instance.storage, instance.lanes, instance.lane_invocations).dispatch(process.process_id, route_result)
        assert result.disposition is RoutingDisposition.LANE
        invocation = instance.lane_invocations.get(result.lane_invocation_id)
        assert invocation.process_id == process.process_id
        assert invocation.lane_id == "diagnose"
        assert invocation.lane_version == 2
        assert invocation.status.value == "CREATED"
    finally:
        instance.stop()


def test_validation_does_not_create_lane_invocation_or_process(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("routing-test")
        instance.lanes.register(make_lane())
        before_invocations = instance.lane_invocations.list(process.process_id)
        RoutingProposalValidator(instance.lanes).validate(
            RoutingProposal(disposition=RoutingDisposition.LANE, lane_id="explore")
        )
        assert instance.lane_invocations.list(process.process_id) == before_invocations
        assert instance.kernel.get(process.process_id).revision == process.revision
    finally:
        instance.stop()


def _dispatch_result(instance: Runtime, process_id: str, proposal: RoutingProposal):
    validated = RoutingProposalValidator(instance.lanes).validate(proposal)
    return RoutingDispatcher(instance.storage, instance.lanes, instance.lane_invocations).dispatch(
        process_id, MainLLMRouteResult(proposal, validated, "attempt", "route")
    )


@pytest.mark.parametrize("disposition", [RoutingDisposition.DIRECT, RoutingDisposition.FALLBACK])
def test_dispatch_non_lane_materializes_explicit_request(tmp_path: Path, disposition: RoutingDisposition):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("dispatch-test")
        proposal = RoutingProposal(
            disposition=disposition,
            inferred_function="novel_cognition" if disposition is RoutingDisposition.FALLBACK else None,
        )
        result = _dispatch_result(instance, process.process_id, proposal)
        assert result.disposition is disposition
        assert result.lane_invocation_id is None
        assert (result.direct_request is not None) is (disposition is RoutingDisposition.DIRECT)
        if result.fallback_request is not None:
            assert result.fallback_request.inferred_function == "novel_cognition"
        assert instance.lane_invocations.list(process.process_id) == []
    finally:
        instance.stop()


def test_dispatch_graph_is_deferred_without_lane_invocation(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        process = instance.kernel.submit("dispatch-test")
        instance.lanes.register(make_lane())
        proposal = RoutingProposal(disposition=RoutingDisposition.GRAPH, graph_proposal={
            "nodes": [{"node_id": "a", "type": "LANE", "lane_id": "explore"}]
        })
        result = _dispatch_result(instance, process.process_id, proposal)
        assert result.graph_plan is not None
        assert result.graph_plan.validated_graph_proposal == proposal.graph_proposal
        assert instance.lane_invocations.list(process.process_id) == []
    finally:
        instance.stop()


def test_dispatch_unknown_process_is_rejected_without_side_effect(tmp_path: Path):
    instance = runtime(tmp_path)
    try:
        proposal = RoutingProposal(disposition=RoutingDisposition.DIRECT)
        with pytest.raises(RoutingDispatchProcessNotFoundError) as exc_info:
            _dispatch_result(instance, "missing-process", proposal)
        assert exc_info.value.code == "ROUTING_DISPATCH_PROCESS_NOT_FOUND"
    finally:
        instance.stop()
