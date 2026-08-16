"""The offline fallback of the eval runner stays deterministic and honest.

The divergence the brief cares about (decomposition-first commits a stale DAG
and its write hits the real SECURITY ERROR, dynamic adapts) is exercised at the
plan-execution level in test_divergence.py. These tests pin the eval runner's
own offline scaffolding: the scripted plans/decisions, the trace->proposal
composer, and the full fallback branches for the new comparison rows.
"""

import pytest

from planning_eval.evaluate_planning import (
    _proposal_from_history,
    _scripted_decisions,
    _scripted_plan,
    evaluate_grounded,
)
from planning_eval.test_cases import SCENARIO_CASES


def test_scripted_plan_omits_verification_for_write_cases():
    case = SCENARIO_CASES[1]  # dispatch bundle
    tasks = {t["id"]: t for t in _scripted_plan(case)["tasks"]}
    assert tasks["write"]["tool"] == "schedule_technician_dispatch"
    assert "verify_account_identity" not in tasks
    # the stale-DAG failure mode: the write depends only on the read
    assert tasks["write"]["depends_on"] == ["diag"]


def test_scripted_plan_has_no_write_for_no_dispatch_case():
    case = SCENARIO_CASES[0]
    tasks = {t["id"]: t for t in _scripted_plan(case)["tasks"]}
    assert set(tasks) == {"diag", "summary"}


def test_scripted_decisions_adapt_after_failed_write():
    case = SCENARIO_CASES[1]
    decisions = _scripted_decisions(case)
    tools = [d["tool"] for d in decisions if d.get("tool")]
    assert tools == [
        "get_equipment_diagnostics",
        "schedule_technician_dispatch",
        "verify_account_identity",
        "schedule_technician_dispatch",
    ]
    assert decisions[-1]["done"] is True


def test_proposal_from_history_maps_successful_writes():
    history = [
        ("get_equipment_diagnostics(...)", "--- Equipment Diagnostics ---"),
        ("schedule_technician_dispatch(...)", "SECURITY ERROR: Account #2 not verified."),
        ("verify_account_identity(...)", "VERIFICATION SUCCESSFUL"),
        ("schedule_technician_dispatch(...)", "SUCCESS: Technician dispatch scheduled"),
    ]
    assert "dispatch a technician" in _proposal_from_history(history).lower()


def test_proposal_from_history_defaults_to_remote_fix():
    history = [("get_equipment_diagnostics(...)", "Status: SYS_OK")]
    assert "no dispatch" in _proposal_from_history(history).lower()


def test_fallback_decomposition_divergence_shows_in_scores():
    """Offline, decomposition-first commits a stale DAG (write node has no
    verify dependency), so on the write cases its own write hits the real
    SECURITY ERROR -> "correct decision, write failed" = 0.5. Dynamic
    decomposition observes the failure, verifies, and re-attempts the write
    -> 1.0. The no-dispatch case has no write, so both resolve it."""
    for case in SCENARIO_CASES:
        expected = case["bundle"]["expected_resolution"]
        static = evaluate_grounded(case, None, "DECOMPOSITION_FIRST")
        dynamic = evaluate_grounded(case, None, "DYNAMIC")
        if expected == "no_dispatch_required":
            assert static["success"] is True and static["score"] == 1.0, case["name"]
        else:
            assert static["success"] is False, case["name"]
            assert static["score"] == 0.5, (case["name"], static["details"])
            assert "write failed" in static["details"]
        assert dynamic["success"] is True and dynamic["score"] == 1.0, case["name"]


def test_fallback_self_refine_and_reflexion_succeed_offline():
    for case in SCENARIO_CASES:
        for method in ("SELF_REFINE", "REFLEXION"):
            result = evaluate_grounded(case, None, method)
            assert result["success"] is True, (case["name"], method, result["details"])
            assert result["score"] == 1.0
