import pytest

from vesper.verification import VerificationError, VerificationReport, VerificationRunner


def test_verification_report_requires_kernel_evidence():
    report = VerificationRunner().run(
        artifact_id="patch-1",
        acceptance_criteria=("tests_pass",),
        execution_results={"tests_pass": {"status": "passed", "command": "pytest -q", "exit_code": 0}},
    )
    assert isinstance(report, VerificationReport)
    assert report.status == "PASSED"
    assert report.evidence[0]["source"] == "kernel"


def test_verification_rejects_model_only_or_nonzero_results():
    runner = VerificationRunner()
    with pytest.raises(VerificationError):
        runner.run("patch-2", ("tests_pass",), {"tests_pass": {"status": "passed", "source": "model"}})
    with pytest.raises(VerificationError):
        runner.run("patch-3", ("tests_pass",), {"tests_pass": {"status": "failed", "exit_code": 1, "source": "kernel"}})


def test_missing_criterion_is_not_passed():
    report = VerificationRunner().run("patch-4", ("tests_pass", "lint_pass"), {"tests_pass": {"status": "passed", "exit_code": 0, "source": "kernel"}})
    assert report.status == "FAILED"
    assert report.failed_criteria == ("lint_pass",)


def test_criteria_and_results_are_immutable_contract_values():
    with pytest.raises(VerificationError):
        VerificationReport("x", "PASSED", (), ("bad",), ())
    with pytest.raises(VerificationError):
        VerificationRunner().run("x", (), {})
