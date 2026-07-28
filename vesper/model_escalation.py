"""Deterministic same-Lane model escalation policy."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class FailureClass(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    STRUCTURED_OUTPUT_INVALID = "structured_output_invalid"
    TOOL_UNRELIABLE = "tool_unreliable"
    VERIFICATION_FAILURE = "verification_failure"
    CONTEXT_OVERFLOW = "context_overflow"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class EscalationResult:
    route_id: str
    lane_id: str
    lane_version: int
    attempt_count: int


class ModelEscalator:
    @staticmethod
    def classify(error: str) -> FailureClass:
        value = str(error).lower()
        if "context" in value and "overflow" in value:
            return FailureClass.CONTEXT_OVERFLOW
        if "timeout" in value:
            return FailureClass.TIMEOUT
        if "provider" in value or "unavailable" in value:
            return FailureClass.PROVIDER_UNAVAILABLE
        if "tool" in value:
            return FailureClass.TOOL_UNRELIABLE
        if "verify" in value or "test" in value:
            return FailureClass.VERIFICATION_FAILURE
        return FailureClass.STRUCTURED_OUTPUT_INVALID

    def select(
        self,
        lane_id: str,
        lane_version: int,
        required_capabilities: frozenset[str],
        routes: tuple[dict[str, Any], ...],
        failure: FailureClass,
        prior_route_id: str | None,
        attempt_count: int,
        max_attempts: int,
    ) -> EscalationResult | None:
        if attempt_count >= max_attempts:
            return None
        eligible = [
            route for route in routes
            if isinstance(route.get("route_id"), str)
            and required_capabilities.issubset(set(route.get("capabilities", ())))
            and isinstance(route.get("reliability"), (int, float))
        ]
        eligible.sort(key=lambda route: (float(route["reliability"]), int(route.get("rank", 0))))
        for route in eligible:
            if route["route_id"] != prior_route_id:
                return EscalationResult(route["route_id"], lane_id, lane_version, attempt_count + 1)
        return None


__all__ = ["EscalationResult", "FailureClass", "ModelEscalator"]
