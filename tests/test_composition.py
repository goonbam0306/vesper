import pytest

from vesper.composition import CompositionError, Composer
from vesper.verification import VerificationRunner


def test_compose_requires_passed_verification_and_preserves_sources():
    report = VerificationRunner().run("patch-1", ("tests_pass",), {"tests_pass": {"status": "passed", "exit_code": 0, "command": "pytest -q"}})
    artifact = Composer().compose(report, title="Implementation result", body="Changed one file")
    assert artifact.artifact_type == "DocumentArtifact"
    assert artifact.sources == ("patch-1",)
    assert "pytest -q" in artifact.body


def test_compose_rejects_failed_verification_or_source_mismatch():
    report = VerificationRunner().run("patch-2", ("tests_pass", "lint_pass"), {"tests_pass": {"status": "passed", "exit_code": 0}})
    with pytest.raises(CompositionError):
        Composer().compose(report, title="bad", body="bad")
