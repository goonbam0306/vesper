from types import SimpleNamespace

import pytest

from vesper.composition import Composer, CompositionError


def test_explore_analyze_compose_requires_kernel_evidence_and_preserves_provenance():
    report = SimpleNamespace(
        status="PASSED",
        artifact_id="analysis-1",
        evidence=({"criterion": "grounded", "source": "kernel", "command": "kernel.verify", "exit_code": 0},),
    )
    artifact = Composer().compose(report, title="Finding", body="Grounded conclusion")
    assert artifact.artifact_type == "DocumentArtifact"
    assert artifact.sources == ("analysis-1",)
    assert "kernel.verify" in artifact.body


def test_compose_rejects_non_kernel_evidence():
    report = SimpleNamespace(status="PASSED", artifact_id="analysis-2", evidence=({"source": "external"},))
    with pytest.raises(CompositionError, match="Kernel evidence"):
        Composer().compose(report, title="Finding", body="Conclusion")
