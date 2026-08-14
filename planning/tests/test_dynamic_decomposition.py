"""Dynamic / interleaved decomposition: the next sub-task is decided only after
observing the result of the previous one, so a runtime surprise reshapes the
plan. Uses real tool observations (including the real auth-gate SECURITY ERROR)."""

from conftest import (
    ScriptedLLM,
    dynamic_flow_known_verified,
    dynamic_flow_that_adapts,
)

from planning import dynamic_decomposition


def test_dynamic_decomposition_adapts_to_security_error(executor):
    """The write is attempted first, rejected by the real auth gate, and only
    then does the next decision insert a verification step (PIN supplied by the
    staff) before re-attempting the write."""
    llm = ScriptedLLM(decisions=dynamic_flow_that_adapts())
    history = dynamic_decomposition(
        "Resolve the outage incident for Walter White (account 2)",
        llm,
        executor=executor,
        credential_provider=lambda account_id: 5678 if account_id == 2 else None,
    )
    results = [result for _, result in history]
    assert any("SECURITY ERROR" in r for r in results)
    assert any("VERIFICATION SUCCESSFUL" in r for r in results)
    assert history[-1][0] == "schedule_technician_dispatch({'account_id': 2, 'description': 'Resolve total internet loss.'})"
    assert "SUCCESS: Technician dispatch scheduled" in history[-1][1]
    # exactly one verify step was inserted, and the write was re-attempted once
    assert sum(1 for label, _ in history if label.startswith("verify_account_identity")) == 1
    assert sum(1 for label, _ in history if label.startswith("schedule_technician_dispatch")) == 2


def test_dynamic_decomposition_asks_staff_when_no_pin_available(executor):
    """If no credential provider can supply the PIN, the loop blocks with an
    AWAITING USER observation instead of guessing."""
    llm = ScriptedLLM(decisions=dynamic_flow_that_adapts())
    history = dynamic_decomposition(
        "Resolve the outage incident for Walter White (account 2)",
        llm,
        executor=executor,
        credential_provider=lambda account_id: None,
    )
    assert history[-1][0] == "REQ-PIN for account #2"
    assert "AWAITING USER" in history[-1][1]
    assert not any("VERIFICATION SUCCESSFUL" in r for _, r in history)


def test_dynamic_matches_static_when_verification_is_known(executor):
    """When the planner already knows the session must be verified, dynamic
    decomposition produces the same successful outcome as a correct static plan."""
    llm = ScriptedLLM(decisions=dynamic_flow_known_verified())
    history = dynamic_decomposition(
        "Resolve the outage incident for Walter White (account 2)",
        llm,
        executor=executor,
        credential_provider=lambda account_id: 5678,
    )
    assert "VERIFICATION SUCCESSFUL" in history[1][1]
    assert "SUCCESS: Technician dispatch scheduled" in history[2][1]


def test_dynamic_requires_executor_for_tool_decisions(executor):
    llm = ScriptedLLM(decisions=dynamic_flow_that_adapts())
    try:
        dynamic_decomposition("Resolve the incident", llm, executor=None)
        assert False, "expected an error"
    except RuntimeError as err:
        assert "no MCP executor was supplied" in str(err)


def test_every_decision_sees_prior_real_observations(executor):
    """The planner prompt on each decision must include every real observation
    made so far -- that is how the SECURITY ERROR reshapes what comes next."""
    llm = ScriptedLLM(decisions=dynamic_flow_that_adapts())
    dynamic_decomposition(
        "Resolve the outage incident for Walter White (account 2)",
        llm,
        executor=executor,
        credential_provider=lambda account_id: 5678,
    )
    decision_prompts = [m[-1][1] for m in llm.prompts if "Decide the single best next task" in m[-1][1]]
    # decision #2 (after the failed write) must carry the real SECURITY ERROR text
    assert any("SECURITY ERROR" in p for p in decision_prompts)