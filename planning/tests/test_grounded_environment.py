"""GroundedEnvironment: feedback from the real DB + auth gate, not keywords.

A wrong decision that still executes is a real $150 cost: it scores 0.3, not
1.0. An unverified session must produce a SECURITY ERROR. These tests prove
the environment's signal comes from executing the real MCP handlers.
"""

from planning.planning_lab.algorithms.environment import (
    GroundedEnvironment,
    _extract_decision,
)
from planning_eval.scenarios import (
    BILLING_BUNDLE_SARAH_BRANDEN,
    FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY,
    OUTAGE_BUNDLE_WALTER_WHITE,
)


def test_extract_decision_handles_negatives_and_positives():
    assert _extract_decision("no dispatch is required here") == "no_dispatch_required"
    assert _extract_decision("send a technician out today") == "dispatch_required"
    assert _extract_decision("apply the credit now") == "credit_applied"
    assert _extract_decision("perform a remote fix over the phone") == "no_dispatch_required"


def test_correct_no_dispatch_decision_succeeds(executor):
    env = GroundedEnvironment(executor, OUTAGE_BUNDLE_WALTER_WHITE)
    feedback = env.evaluate("No dispatch needed; resolve remotely.")
    assert feedback.success
    assert feedback.score == 1.0
    writes = [c for c in executor.call_log if c["tool"] in env.WRITE_TOOLS]
    assert writes == []


def test_wrong_dispatch_is_an_expensive_failure(executor):
    env = GroundedEnvironment(executor, OUTAGE_BUNDLE_WALTER_WHITE)
    feedback = env.evaluate("Dispatch a technician right now.")
    assert not feedback.success
    assert feedback.score == 0.3
    writes = [c for c in executor.call_log if c["tool"] == "schedule_technician_dispatch"]
    assert len(writes) == 1
    assert "SUCCESS" in writes[0]["result"]


def test_correct_dispatch_for_faulty_modem_succeeds(executor):
    env = GroundedEnvironment(executor, FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    feedback = env.evaluate("Dispatch a technician to fix the hardware fault.")
    assert feedback.success
    assert feedback.score == 1.0
    assert "SUCCESS" in executor.call_log[-1]["result"]


def test_credit_succeeds_only_with_matching_decision_and_ticket(executor):
    env = GroundedEnvironment(executor, BILLING_BUNDLE_SARAH_BRANDEN, ticket_id=1, credit_amount_usd=30.0)
    feedback = env.evaluate("Apply the $30 billing credit to the account.")
    assert feedback.success
    assert feedback.score == 1.0
    assert "SUCCESS: Applied $30.00 credit" in executor.call_log[-1]["result"]


def test_unverified_session_blocks_write_when_no_pin(executor):
    scenario = dict(FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    scenario["pin"] = None
    env = GroundedEnvironment(executor, scenario)
    feedback = env.evaluate("Dispatch a technician.")
    assert not feedback.success
    assert feedback.score == 0.5
    assert "SECURITY ERROR" in feedback.details


def test_wrong_decision_with_failed_write_scores_lowest(executor):
    scenario = dict(OUTAGE_BUNDLE_WALTER_WHITE)
    scenario["pin"] = 0000
    env = GroundedEnvironment(executor, scenario, ticket_id=1)
    feedback = env.evaluate("Apply a $30 credit.")  # wrong decision, wrong PIN -> write blocked
    assert not feedback.success
    assert feedback.score == 0.1
