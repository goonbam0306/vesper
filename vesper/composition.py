"""Source-faithful composition from verified artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .verification import VerificationReport


class CompositionError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentArtifact:
    artifact_type: str
    title: str
    body: str
    sources: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]


class Composer:
    def compose(self, report: VerificationReport, *, title: str, body: str) -> DocumentArtifact:
        if report.status != "PASSED":
            raise CompositionError("only passed verification reports may be composed")
        _ensure_kernel_report(report)
        if not title or not body:
            raise CompositionError("title and body are required")
        evidence_lines = [
            f"- {item['criterion']}: {item.get('command', 'kernel execution')} (exit {item.get('exit_code')})"
            for item in report.evidence
        ]
        rendered = f"{body}\n\nVerification evidence:\n" + "\n".join(evidence_lines)
        return DocumentArtifact("DocumentArtifact", title, rendered, (report.artifact_id,), report.evidence)


__all__ = ["CompositionError", "Composer", "DocumentArtifact"]


def _ensure_kernel_report(report: VerificationReport) -> None:
    if any(item.get("source") != "kernel" for item in report.evidence):
        raise CompositionError("composition requires Kernel evidence")
