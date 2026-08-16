"""resolve_with_self_correction(): the integration point the live planning
agent calls once it has a proposal and wants it checked and, if necessary,
corrected against the real GroundedEnvironment before anything is written
for real. See `planning/self_correction.py`.
"""
from planning.planning_lab.algorithms.environment import GroundedEnvironment
from planning.self_correction import resolve_with_self_correction
from planning.tests.conftest import ScriptedLLM
from planning_eval.scenarios import FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY

GOAL = FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY["staff_request"]
CORRECT_DRAFT = "Dispatch a technician to fix the hardware fault."


def test_already_correct_proposal_needs_no_correction(executor):
    env = GroundedEnvironment(executor, FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    llm = ScriptedLLM(prose="should not be called")

    result = resolve_with_self_correction(GOAL, CORRECT_DRAFT, llm, env)

    assert result.success
    assert result.method_used == "none-needed"
    assert llm.llm_calls == 0  # no model call needed at all


def test_wrong_proposal_is_fixed_by_self_refine(executor):
    env = GroundedEnvironment(executor, FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    llm = ScriptedLLM(responses=[
        ("Return only the improved deliverable", CORRECT_DRAFT),
        ("External checks", "Dispatch is required per the grounded diagnostics."),
    ])

    result = resolve_with_self_correction(GOAL, "No dispatch needed; resolve remotely.", llm, env)

    assert result.success
    assert result.method_used == "self-refine"
    assert result.output == CORRECT_DRAFT
    assert result.reflexion_result is None  # Reflexion was never needed


def test_hard_proposal_escalates_to_reflexion_after_self_refine_fails(executor):
    """If Self-Refine's one revision is still wrong, escalate to Reflexion
    rather than giving up or returning a still-broken proposal."""
    env = GroundedEnvironment(executor, FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    llm = ScriptedLLM(responses=[
        # Self-Refine's one revision call still gets it wrong.
        ("Return only the improved deliverable", "No dispatch needed; resolve remotely."),
        ("External checks", "Something is still not right about this proposal."),
        # Reflexion's own trials: trial 1 (re-attempts the same wrong text),
        # then a real lesson, then a correct trial 2.
        ("No prior trials.", "No dispatch needed; resolve remotely."),
        ("first-person Reflexion memory",
         "I proposed the wrong resolution; dispatch is required per the diagnostics."),
        ("dispatch is required", CORRECT_DRAFT),
    ])

    result = resolve_with_self_correction(
        GOAL, "No dispatch needed; resolve remotely.", llm, env, max_trials=3, memory_size=2,
    )

    assert result.success
    assert result.method_used == "reflexion"
    assert result.output == CORRECT_DRAFT
    assert result.self_refine_result is not None
    assert result.reflexion_result is not None
