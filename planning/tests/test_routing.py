"""Routing: pure decision logic mapping a sub-task's shape to a method."""

from planning.routing import PlanningMethod, route_subtask
from planning.planning_test_cases import SCENARIO_CASES


def test_linear_subtask_routes_to_plan_and_solve():
    decision = route_subtask("fetch diagnostics", mostly_deterministic=True)
    assert decision.method == PlanningMethod.PLAN_AND_SOLVE
    assert "linear" in decision.reason.lower()


def test_branching_subtask_routes_to_tree_of_thoughts():
    decision = route_subtask("pick a resolution", requires_branching=True, requires_lookahead=True)
    assert decision.method == PlanningMethod.TREE_OF_THOUGHTS


def test_external_validation_routes_to_lats():
    decision = route_subtask("apply a write", requires_external_validation=True)
    assert decision.method == PlanningMethod.LATS
    assert "external validation" in decision.reason.lower()


def test_external_validation_wins_over_branching():
    decision = route_subtask(
        "anything",
        requires_branching=True,
        requires_lookahead=True,
        requires_external_validation=True,
    )
    assert decision.method == PlanningMethod.LATS


def test_default_without_flags_is_plan_and_solve():
    decision = route_subtask("summarise the incident")
    assert decision.method == PlanningMethod.PLAN_AND_SOLVE


def test_scenario_shapes_route_as_designed():
    decisions = {
        case["name"]: route_subtask(case["name"], **case["shape"]).method
        for case in SCENARIO_CASES
    }
    assert decisions["Outage bundle - Walter White (no dispatch)"] == PlanningMethod.PLAN_AND_SOLVE
    assert decisions["Faulty modem bundle - Ellen Ripley (dispatch)"] == PlanningMethod.LATS
    assert decisions["Billing bundle - Sarah Branden (credit)"] == PlanningMethod.LATS
