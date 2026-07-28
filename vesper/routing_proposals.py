"""Typed cognitive routing proposals and deterministic Kernel validation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from .lane_invocations import LaneInvocationStore
from .lanes import LaneNotFoundError, LaneRegistry, LaneVersionNotFoundError
from .model_runtime import CognitiveRequest, CognitiveRuntime, ModelRoute


class RoutingDisposition(StrEnum):
    DIRECT = "DIRECT"
    LANE = "LANE"
    GRAPH = "GRAPH"
    FALLBACK = "FALLBACK"


class RoutingProposalError(RuntimeError):
    code = "ROUTING_PROPOSAL_INVALID"


class RoutingDispositionInvalidError(RoutingProposalError):
    code = "ROUTING_DISPOSITION_INVALID"


class RoutingLaneNotFoundError(RoutingProposalError):
    code = "ROUTING_LANE_NOT_FOUND"


class RoutingLaneDisabledError(RoutingProposalError):
    code = "ROUTING_LANE_DISABLED"


class RoutingGraphInvalidError(RoutingProposalError):
    code = "ROUTING_GRAPH_INVALID"


class RoutingFallbackInvalidError(RoutingProposalError):
    code = "ROUTING_FALLBACK_INVALID"


@dataclass(frozen=True)
class RoutingProposal:
    disposition: RoutingDisposition | str
    proposal_id: str | None = None
    lane_id: str | None = None
    lane_version: int | None = None
    graph_proposal: Any | None = None
    inferred_function: str | None = None
    required_capabilities: frozenset[str] = frozenset()
    requested_context: tuple[str, ...] = ()
    confidence: float | None = None
    rationale_summary: str | None = None


@dataclass(frozen=True)
class ValidatedRoutingProposal:
    proposal: RoutingProposal
    resolved_lane_id: str | None = None
    resolved_lane_version: int | None = None


class RoutingAdapterError(RoutingProposalError):
    code = "ROUTING_ADAPTER_FAILED"


class RoutingOutputMalformedError(RoutingAdapterError):
    code = "ROUTING_OUTPUT_MALFORMED"


class RoutingDispatchError(RoutingProposalError):
    code = "ROUTING_DISPATCH_INVALID_INPUT"


class RoutingDispatchProcessNotFoundError(RoutingDispatchError):
    code = "ROUTING_DISPATCH_PROCESS_NOT_FOUND"


class RoutingDispatchUnsupportedError(RoutingDispatchError):
    code = "ROUTING_DISPATCH_UNSUPPORTED"


@dataclass(frozen=True)
class DirectCognitionRequest:
    process_id: str
    user_request: str | None = None


@dataclass(frozen=True)
class FallbackCognitionRequest:
    process_id: str
    inferred_function: str


@dataclass(frozen=True)
class GraphMaterializationPending:
    process_id: str
    validated_graph_proposal: Any


@dataclass(frozen=True)
class RoutingDispatchResult:
    disposition: RoutingDisposition
    lane_invocation_id: str | None = None
    direct_request: DirectCognitionRequest | None = None
    fallback_request: FallbackCognitionRequest | None = None
    graph_plan: GraphMaterializationPending | None = None
    routing_attempt_id: str | None = None
    model_route_id: str | None = None


@dataclass(frozen=True)
class MainLLMRouteResult:
    raw: RoutingProposal
    validated: ValidatedRoutingProposal
    attempt_id: str
    model_route_id: str


class RoutingDispatcher:
    """Materialize only the runtime state permitted by a validated route."""

    def __init__(self, storage: Any, lanes: LaneRegistry, invocations: LaneInvocationStore) -> None:
        self.storage = storage
        self.lanes = lanes
        self.invocations = invocations

    def dispatch(self, process_id: str, route_result: MainLLMRouteResult) -> RoutingDispatchResult:
        if not isinstance(process_id, str) or not process_id.strip():
            raise RoutingDispatchProcessNotFoundError("process_id is required")
        if not isinstance(route_result, MainLLMRouteResult) or not isinstance(route_result.validated, ValidatedRoutingProposal):
            raise RoutingDispatchError("dispatch requires a MainLLMRouteResult with validated proposal")
        process = self.storage.write(lambda conn: conn.execute("SELECT 1 FROM processes WHERE process_id=?", (process_id,)).fetchone())
        if process is None:
            raise RoutingDispatchProcessNotFoundError("process not found")
        validated = route_result.validated
        disposition = RoutingDisposition(validated.proposal.disposition)
        if disposition is RoutingDisposition.LANE:
            if validated.resolved_lane_id is None or validated.resolved_lane_version is None:
                raise RoutingDispatchError("validated LANE route lacks resolved Lane identity")
            invocation = self.invocations.create(process_id, validated.resolved_lane_id, version=validated.resolved_lane_version, model_route_id=route_result.model_route_id)
            return RoutingDispatchResult(
                disposition=disposition,
                lane_invocation_id=invocation.invocation_id,
                routing_attempt_id=route_result.attempt_id,
                model_route_id=route_result.model_route_id,
            )
        if disposition is RoutingDisposition.DIRECT:
            return RoutingDispatchResult(
                disposition=disposition,
                direct_request=DirectCognitionRequest(process_id),
                routing_attempt_id=route_result.attempt_id,
                model_route_id=route_result.model_route_id,
            )
        if disposition is RoutingDisposition.FALLBACK:
            inferred = validated.proposal.inferred_function
            if not isinstance(inferred, str) or not inferred.strip():
                raise RoutingDispatchError("validated FALLBACK route lacks inferred_function")
            return RoutingDispatchResult(
                disposition=disposition,
                fallback_request=FallbackCognitionRequest(process_id, inferred),
                routing_attempt_id=route_result.attempt_id,
                model_route_id=route_result.model_route_id,
            )
        if disposition is RoutingDisposition.GRAPH:
            return RoutingDispatchResult(
                disposition=disposition,
                graph_plan=GraphMaterializationPending(process_id, validated.proposal.graph_proposal),
                routing_attempt_id=route_result.attempt_id,
                model_route_id=route_result.model_route_id,
            )
        raise RoutingDispatchUnsupportedError("unsupported routing disposition")


class MainLLMRouter:
    """Convert one bounded Main LLM response into a validated route proposal."""

    def __init__(self, cognitive: CognitiveRuntime, lanes: LaneRegistry) -> None:
        self.cognitive = cognitive
        self.lanes = lanes
        self.validator = RoutingProposalValidator(lanes)

    def route(
        self,
        process_id: str,
        user_request: str,
        *,
        context: Any | None = None,
        route: ModelRoute | None = None,
    ) -> MainLLMRouteResult:
        contract = self.build_routing_contract(user_request, context=context)
        try:
            result = self.cognitive.invoke_model(
                process_id,
                CognitiveRequest(privacy="local_preferred"),
                contract,
                route=route,
            )
        except Exception as exc:
            if isinstance(exc, RoutingAdapterError):
                raise
            raise RoutingAdapterError("routing model invocation failed") from exc
        if not result.success or result.output is None:
            raise RoutingAdapterError(result.response.error or "routing model invocation failed")
        proposal = self.parse_output(result.output)
        validated = self.validator.validate(proposal)
        return MainLLMRouteResult(proposal, validated, result.attempt.attempt_id, result.route.route_id)

    def build_routing_contract(self, user_request: str, *, context: Any | None = None) -> dict[str, Any]:
        if not isinstance(user_request, str) or not user_request.strip():
            raise RoutingOutputMalformedError("user_request must be non-empty")
        lanes = []
        for lane in self.lanes.list():
            if lane.enabled:
                lanes.append({"lane_id": lane.lane_id, "purpose": lane.purpose, "capabilities": lane.capability_requirements})
        return {
            "task": "Return exactly one JSON RoutingProposal for the user request.",
            "routing_contract": {
                "dispositions": {
                    "DIRECT": "No specialized functional execution is required.",
                    "LANE": "Use one enabled bounded Lane.",
                    "GRAPH": "Use multiple LANE nodes with dependencies only.",
                    "FALLBACK": "No enabled Lane adequately represents the required cognition; provide inferred_function.",
                },
                "graph_node_types": ["LANE"],
                "deterministic_graph_nodes": "deferred to Phase 6F",
            },
            "user_request": user_request,
            "context": context if context is not None else {},
            "available_lanes": lanes,
            "output_schema": "RoutingProposal JSON object; do not include chain-of-thought.",
        }

    @staticmethod
    def parse_output(output: str) -> RoutingProposal:
        if not isinstance(output, str) or not output.strip():
            raise RoutingOutputMalformedError("model output must be non-empty JSON")
        try:
            value = json.loads(output)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RoutingOutputMalformedError("model output is not valid JSON") from exc
        if not isinstance(value, Mapping):
            raise RoutingOutputMalformedError("model output must be a JSON object")
        allowed = {"proposal_id", "disposition", "lane_id", "lane_version", "graph_proposal", "inferred_function", "required_capabilities", "requested_context", "confidence", "rationale_summary"}
        unknown = set(value) - allowed
        if unknown:
            raise RoutingOutputMalformedError("model output contains unknown fields")
        if "disposition" not in value:
            raise RoutingOutputMalformedError("model output is missing disposition")
        capabilities = value.get("required_capabilities", [])
        context = value.get("requested_context", [])
        if isinstance(capabilities, list):
            capabilities = frozenset(capabilities)
        if isinstance(context, list):
            context = tuple(context)
        try:
            disposition = RoutingDisposition(value["disposition"])
        except (TypeError, ValueError) as exc:
            raise RoutingDispositionInvalidError("unknown disposition") from exc
        return RoutingProposal(
            disposition=disposition, proposal_id=value.get("proposal_id"), lane_id=value.get("lane_id"),
            lane_version=value.get("lane_version"), graph_proposal=value.get("graph_proposal"),
            inferred_function=value.get("inferred_function"), required_capabilities=capabilities,
            requested_context=context, confidence=value.get("confidence"), rationale_summary=value.get("rationale_summary"),
        )


class RoutingProposalValidator:
    """Validate proposal shape and Lane registry references; never execute effects."""

    def __init__(self, lanes: LaneRegistry) -> None:
        self.lanes = lanes

    def validate(self, proposal: RoutingProposal) -> ValidatedRoutingProposal:
        if not isinstance(proposal, RoutingProposal):
            raise RoutingProposalError("proposal must be a RoutingProposal")
        disposition = self._disposition(proposal.disposition)
        self._validate_common(proposal)
        self._reject_cross_disposition_fields(proposal, disposition)
        if disposition is RoutingDisposition.DIRECT:
            return ValidatedRoutingProposal(proposal)
        if disposition is RoutingDisposition.LANE:
            return self._validate_lane(proposal)
        if disposition is RoutingDisposition.GRAPH:
            self._validate_graph(proposal.graph_proposal)
            return ValidatedRoutingProposal(proposal)
        if not isinstance(proposal.inferred_function, str) or not proposal.inferred_function.strip():
            raise RoutingFallbackInvalidError("inferred_function is required")
        if len(proposal.inferred_function.strip()) > 128:
            raise RoutingFallbackInvalidError("inferred_function exceeds 128 characters")
        return ValidatedRoutingProposal(proposal)

    @staticmethod
    def _disposition(value: RoutingDisposition | str) -> RoutingDisposition:
        try:
            return RoutingDisposition(value)
        except (ValueError, TypeError) as exc:
            raise RoutingDispositionInvalidError("unknown disposition") from exc

    @staticmethod
    def _validate_common(proposal: RoutingProposal) -> None:
        if proposal.proposal_id is not None and (not isinstance(proposal.proposal_id, str) or not proposal.proposal_id.strip()):
            raise RoutingProposalError("proposal_id must be a non-empty string")
        if proposal.lane_version is not None and (not isinstance(proposal.lane_version, int) or isinstance(proposal.lane_version, bool) or proposal.lane_version <= 0):
            raise RoutingProposalError("lane_version must be a positive integer")
        if not isinstance(proposal.required_capabilities, (frozenset, set, tuple, list)) or not all(isinstance(v, str) and v.strip() for v in proposal.required_capabilities):
            raise RoutingProposalError("required_capabilities must contain non-empty strings")
        if not isinstance(proposal.requested_context, (tuple, list)) or not all(isinstance(v, str) and v.strip() for v in proposal.requested_context):
            raise RoutingProposalError("requested_context must contain non-empty strings")
        if proposal.confidence is not None and (isinstance(proposal.confidence, bool) or not isinstance(proposal.confidence, (int, float)) or not 0 <= proposal.confidence <= 1):
            raise RoutingProposalError("confidence must be between 0 and 1")
        if proposal.rationale_summary is not None and (not isinstance(proposal.rationale_summary, str) or len(proposal.rationale_summary) > 512):
            raise RoutingProposalError("rationale_summary must be at most 512 characters")

    @staticmethod
    def _reject_cross_disposition_fields(proposal: RoutingProposal, disposition: RoutingDisposition) -> None:
        if disposition is RoutingDisposition.DIRECT and any(v is not None for v in (proposal.lane_id, proposal.lane_version, proposal.graph_proposal, proposal.inferred_function)):
            raise RoutingProposalError("DIRECT proposal has contradictory routing fields")
        if disposition is RoutingDisposition.LANE and proposal.graph_proposal is not None:
            raise RoutingProposalError("LANE proposal cannot contain graph_proposal")
        if disposition is RoutingDisposition.GRAPH and any(v is not None for v in (proposal.lane_id, proposal.lane_version, proposal.inferred_function)):
            raise RoutingProposalError("GRAPH proposal has contradictory routing fields")
        if disposition is RoutingDisposition.FALLBACK and any(v is not None for v in (proposal.lane_id, proposal.lane_version, proposal.graph_proposal)):
            raise RoutingProposalError("FALLBACK proposal has contradictory routing fields")

    def _validate_lane(self, proposal: RoutingProposal) -> ValidatedRoutingProposal:
        if not isinstance(proposal.lane_id, str) or not proposal.lane_id.strip():
            raise RoutingLaneNotFoundError("LANE proposal requires lane_id")
        try:
            lane = self.lanes.latest(proposal.lane_id) if proposal.lane_version is None else self.lanes.get(proposal.lane_id, proposal.lane_version)
        except LaneVersionNotFoundError as exc:
            raise RoutingLaneNotFoundError("lane version not found") from exc
        except LaneNotFoundError as exc:
            raise RoutingLaneNotFoundError("enabled lane not found") from exc
        if not lane.enabled:
            raise RoutingLaneDisabledError("lane version is disabled")
        return ValidatedRoutingProposal(proposal, lane.lane_id, lane.version)

    def _validate_graph(self, graph: Any) -> None:
        if not isinstance(graph, Mapping):
            raise RoutingGraphInvalidError("graph_proposal must be a structured mapping")
        nodes = graph.get("nodes")
        if not isinstance(nodes, (list, tuple)) or not nodes or len(nodes) > 64:
            raise RoutingGraphInvalidError("graph nodes must contain 1..64 items")
        identifiers: set[str] = set()
        for node in nodes:
            if not isinstance(node, Mapping) or not isinstance(node.get("node_id"), str) or not node["node_id"].strip() or node["node_id"] in identifiers:
                raise RoutingGraphInvalidError("graph node identifiers must be unique non-empty strings")
            # GRAPH nodes currently represent Lane work only. Top-level DIRECT is
            # not a graph node; deterministic operation nodes are deferred to the
            # Phase 6F Execution Graph runtime.
            if node.get("type") != "LANE":
                raise RoutingGraphInvalidError("only LANE graph nodes are supported; deterministic nodes are deferred to Phase 6F")
            identifiers.add(node["node_id"])
        for node in nodes:
            dependencies = node.get("dependencies", ())
            if not isinstance(dependencies, (list, tuple)) or not all(dep in identifiers for dep in dependencies):
                raise RoutingGraphInvalidError("graph dependency references an unknown node")
            if node["type"] == "LANE":
                lane_id = node.get("lane_id")
                if not isinstance(lane_id, str) or not lane_id.strip():
                    raise RoutingGraphInvalidError("LANE graph node requires lane_id")
                try:
                    self.lanes.latest(lane_id)
                except LaneNotFoundError as exc:
                    raise RoutingGraphInvalidError("graph Lane target is not enabled") from exc
        return None
