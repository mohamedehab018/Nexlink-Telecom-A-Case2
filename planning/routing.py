from enum import Enum

class PlanningMethod(str, Enum):
    PLAN_AND_SOLVE = "PS"
    TREE_OF_THOUGHTS = "ToT"
    LATS = "LATS"

class PlanningDecision:
    def __init__(self, method: PlanningMethod, reason: str):
        self.method = method
        self.reason = reason

def route_subtask(
    subtask: str,
    requires_branching: bool = False,
    requires_lookahead: bool = False,
    requires_external_validation: bool = False,
    mostly_deterministic: bool = False,
) -> PlanningDecision:
    if requires_external_validation:
        return PlanningDecision(
            method=PlanningMethod.LATS,
            reason="Sub-task needs external validation; LATS uses environment feedback."
        )
    if requires_branching or requires_lookahead:
        return PlanningDecision(
            method=PlanningMethod.TREE_OF_THOUGHTS,
            reason="Sub-task has multiple alternatives; Tree of Thoughts explores branches."
        )
    if mostly_deterministic:
        return PlanningDecision(
            method=PlanningMethod.PLAN_AND_SOLVE,
            reason="Sub-task is linear; Plan-and-Solve avoids unnecessary search."
        )
    return PlanningDecision(
        method=PlanningMethod.PLAN_AND_SOLVE,
        reason="No branching or validation required; using cheaper linear planning."
    )
