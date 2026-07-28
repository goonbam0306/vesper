import pytest

from vesper.adaptive_execution import (
    ContextNeed,
    GraphRevisionRequest,
    LaneOutcome,
    LaneOutcomeDisposition,
    LaneOutcomeValidationError,
    LaneOutcomeValidator,
    ProposedWorkUnit,
    WorkExpansionProposal,
)


def valid_complete():
    return LaneOutcome(LaneOutcomeDisposition.COMPLETE)


def test_complete_validates_and_unknown_disposition_is_rejected():
    assert LaneOutcomeValidator.validate(valid_complete()) == valid_complete()
    with pytest.raises((ValueError, LaneOutcomeValidationError)):
        LaneOutcome("NOT_A_DISPOSITION")


def test_need_context_requires_structured_context_need():
    need = ContextNeed(reason="missing caller map", requested_refs_or_kinds=("caller_map",))
    assert LaneOutcomeValidator.validate(LaneOutcome(LaneOutcomeDisposition.NEED_CONTEXT, control_request=need))
    with pytest.raises(LaneOutcomeValidationError):
        LaneOutcomeValidator.validate(LaneOutcome(LaneOutcomeDisposition.NEED_CONTEXT))


def test_expand_requires_proposal_and_never_creates_invocation():
    proposal = WorkExpansionProposal(
        reason="independent paths discovered",
        proposed_work_units=(
            ProposedWorkUnit("retry", "Explore", "investigate retry path"),
            ProposedWorkUnit("webhook", "Explore", "investigate webhook path"),
        ),
    )
    outcome = LaneOutcome(LaneOutcomeDisposition.EXPAND, control_request=proposal)
    assert LaneOutcomeValidator.validate(outcome) == outcome
    assert not hasattr(proposal, "lane_invocation")
    with pytest.raises(LaneOutcomeValidationError):
        LaneOutcomeValidator.validate(LaneOutcome(LaneOutcomeDisposition.EXPAND))


def test_replan_requires_evidence_and_invalidated_assumptions():
    request = GraphRevisionRequest(
        reason="auth model is incompatible with SSO",
        new_evidence_refs=("artifact://diagnosis/1",),
        invalidated_assumptions=("auth is a narrow bug",),
    )
    outcome = LaneOutcome(LaneOutcomeDisposition.REPLAN, control_request=request)
    assert LaneOutcomeValidator.validate(outcome) == outcome
    with pytest.raises(LaneOutcomeValidationError):
        LaneOutcomeValidator.validate(
            LaneOutcome(LaneOutcomeDisposition.REPLAN, control_request=GraphRevisionRequest(reason="x"))
        )


@pytest.mark.parametrize(
    "outcome",
    [
        LaneOutcome(LaneOutcomeDisposition.COMPLETE, control_request=object()),
        LaneOutcome(LaneOutcomeDisposition.EXPAND, control_request=GraphRevisionRequest(reason="x")),
        LaneOutcome(LaneOutcomeDisposition.REPLAN, control_request=WorkExpansionProposal(reason="x", proposed_work_units=())),
    ],
)
def test_contradictory_payloads_are_rejected(outcome):
    with pytest.raises(LaneOutcomeValidationError):
        LaneOutcomeValidator.validate(outcome)


def test_blocked_and_fail_require_structured_metadata():
    assert LaneOutcomeValidator.validate(
        LaneOutcome(LaneOutcomeDisposition.BLOCKED, control_request={"reason": "approval", "category": "approval"})
    )
    assert LaneOutcomeValidator.validate(
        LaneOutcome(LaneOutcomeDisposition.FAIL, control_request={"classification": "PROVIDER_ERROR", "reason": "down"})
    )
    with pytest.raises(LaneOutcomeValidationError):
        LaneOutcomeValidator.validate(LaneOutcome(LaneOutcomeDisposition.BLOCKED))
    with pytest.raises(LaneOutcomeValidationError):
        LaneOutcomeValidator.validate(LaneOutcome(LaneOutcomeDisposition.FAIL))