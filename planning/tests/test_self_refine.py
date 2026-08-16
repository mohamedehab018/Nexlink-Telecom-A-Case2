"""Self-Refine grounded in the real database, not text heuristics.

Uses the project's existing `executor`/`db_path` fixtures (conftest.py) so
every check here runs against a real, isolated copy of `db/nexlink.db` and
the real MCP write handlers -- the same infrastructure
`test_grounded_environment.py` already relies on.
"""
from planning.planning_lab.algorithms.environment import GroundedEnvironment
from planning.planning_lab.algorithms.self_refine import (
    deterministic_checks,
    reflect_and_refine,
    ungrounded_critique,
)
from planning.tests.conftest import ScriptedLLM
from planning_eval.scenarios import FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY

GOAL = FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY["staff_request"]
WRONG_DRAFT = "No dispatch needed; resolve remotely."
CORRECT_DRAFT = "Dispatch a technician to fix the hardware fault."


def test_deterministic_checks_unchanged_when_no_environment_given():
    """Backward compatibility: reflect_and_refine() with no `environment`
    still behaves exactly like the original toolkit function."""
    llm = ScriptedLLM(prose=CORRECT_DRAFT, responses=[("External checks", "PASS")])
    result = reflect_and_refine(GOAL, CORRECT_DRAFT * 20, llm)  # long enough to pass length check
    assert result.grounded_source == "ungrounded:deterministic_checks"
    assert result.grounded_issues == deterministic_checks(GOAL, CORRECT_DRAFT * 20)


def test_reflect_and_refine_uses_grounded_environment_when_given(executor):
    """The critique/revision prompts see the REAL grounded failure (wrong
    ticket/decision, executed via the real MCP handlers), not a keyword
    heuristic -- and one revision call produces a draft the same
    GroundedEnvironment accepts."""
    env = GroundedEnvironment(executor, FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    llm = ScriptedLLM(responses=[
        # More specific needle first: both prompts contain "External checks",
        # but only the revision prompt asks to "Return only the improved
        # deliverable" -- ScriptedLLM returns the first matching needle, so
        # order here matters.
        ("Return only the improved deliverable", CORRECT_DRAFT),
        ("External checks", "The resolution proposes remote fix, but the grounded check "
                              "shows dispatch is the expected decision. This must change."),
    ])

    result = reflect_and_refine(GOAL, WRONG_DRAFT, llm, environment=env)

    assert result.grounded_source == "grounded:GroundedEnvironment"
    assert result.grounded_issues  # the initial wrong draft failed, so issues are non-empty
    assert result.revised == CORRECT_DRAFT
    # Confirm the fix is REAL: the grounded environment now accepts it.
    assert env.evaluate(result.revised).success


def test_reflect_and_refine_skips_revision_when_already_grounded_correct(executor):
    """An already-correct draft should not trigger an unnecessary revision
    call, and the trace-log details should NOT be reported as "issues"."""
    env = GroundedEnvironment(executor, FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    llm = ScriptedLLM(responses=[("External checks", "PASS")])

    result = reflect_and_refine(GOAL, CORRECT_DRAFT, llm, environment=env)

    assert result.grounded_issues == []  # trace log, not issues, when the check passed
    assert result.revised == CORRECT_DRAFT  # unchanged: no revision call was needed


def test_independent_critic_can_differ_from_the_revising_model(executor):
    """`critic` may be a different model than `llm`; reflect_and_refine()
    must route the critique call there, not to `llm`."""
    env = GroundedEnvironment(executor, FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    reviser = ScriptedLLM(responses=[("Return only the improved deliverable", CORRECT_DRAFT)])
    critic = ScriptedLLM(responses=[("External checks", "A different model flags the same issue.")])

    result = reflect_and_refine(GOAL, WRONG_DRAFT, reviser, environment=env, critic=critic)

    assert critic.llm_calls == 1   # only the critique went to the independent critic
    assert reviser.llm_calls == 1  # only the revision went to the reviser
    assert "different model" in result.critique


def test_grounded_vs_ungrounded_critique_on_the_same_wrong_draft(executor):
    """The lab's required grounded-vs-ungrounded contrast: an ungrounded
    critic (no DB access) can rubber-stamp the SAME draft the real,
    DB-executing GroundedEnvironment correctly rejects."""
    env = GroundedEnvironment(executor, FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    ungrounded_llm = ScriptedLLM(prose="PASS")

    ungrounded_verdict = ungrounded_critique(WRONG_DRAFT, ungrounded_llm)
    grounded_feedback = env.evaluate(WRONG_DRAFT)

    assert ungrounded_verdict.strip().upper() == "PASS"  # ungrounded: accepts it
    assert not grounded_feedback.success                  # grounded: correctly rejects it
