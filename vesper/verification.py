"""Deterministic verification reports backed only by Kernel execution evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class VerificationError(ValueError):
    pass


@dataclass(frozen=True)
class VerificationReport:
    artifact_id: str
    status: str
    evidence: tuple[dict[str, Any], ...]
    failed_criteria: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise VerificationError("artifact_id is required")
        if self.status not in {"PASSED", "FAILED"}:
            raise VerificationError("invalid verification status")
        if not self.acceptance_criteria:
            raise VerificationError("acceptance criteria are required")


class VerificationRunner:
    def run(
        self,
        artifact_id: str,
        acceptance_criteria: tuple[str, ...],
        execution_results: dict[str, dict[str, Any]],
    ) -> VerificationReport:
        if not artifact_id or not acceptance_criteria:
            raise VerificationError("artifact and acceptance criteria are required")
        evidence: list[dict[str, Any]] = []
        failed: list[str] = []
        for criterion in acceptance_criteria:
            result = execution_results.get(criterion)
            if result is None:
                failed.append(criterion)
                continue
            if result.get("source", "kernel") != "kernel":
                raise VerificationError(f"criterion is not backed by Kernel evidence: {criterion}")
            if result.get("status") != "passed" or result.get("exit_code") != 0:
                raise VerificationError(f"Kernel execution failed for criterion: {criterion}")
            evidence.append({"criterion": criterion, **result, "source": "kernel"})
        return VerificationReport(
            artifact_id=artifact_id,
            status="PASSED" if not failed else "FAILED",
            evidence=tuple(evidence),
            failed_criteria=tuple(failed),
            acceptance_criteria=tuple(acceptance_criteria),
        )
