"""Reflexion grounded in the real database, with a real capped episodic
buffer -- and a concrete demonstration of why the toolkit's fake randomized
`Environment` must never be the one actually used.
"""
from planning.planning_lab.algorithms.environment import Environment, GroundedEnvironment
from planning.planning_lab.algorithms.reflexion import reflexion
from planning.tests.conftest import ScriptedLLM
from planning_eval.scenarios import FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY, OUTAGE_BUNDLE_WALTER_WHITE

GOAL = FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY["staff_request"]


def test_fake_environment_ignores_input_grounded_environment_does_not(executor):
    """The exact risk Issue #1 flags: the toolkit's `Environment` never
    looks at the candidate at all, so even at the strictest possible
    threshold it accepts a wrong proposal that `GroundedEnvironment`
    -- which actually executes the real MCP handlers -- correctly rejects."""
    wrong_draft = "Dispatch a technician right now."  # wrong for Walter White's bundle

    fake = Environment(success_threshold=0.0)  # the "safest" possible setting
    assert fake.evaluate(wrong_draft).success  # accepts ANY input whatsoever

    real = GroundedEnvironment(executor, OUTAGE_BUNDLE_WALTER_WHITE)
    assert not real.evaluate(wrong_draft).success  # correctly rejects the same input


def test_reflexion_converges_using_the_grounded_environment(executor):
    """Trial 1's naive attempt fails against the real GroundedEnvironment;
    the resulting lesson is carried into trial 2's attempt, which succeeds --
    and the success is checked by ACTUALLY executing the real MCP handlers,
    not a keyword or fake score."""
    env = GroundedEnvironment(executor, FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY)
    llm = ScriptedLLM(responses=[
        ("No prior trials.", "No dispatch needed; resolve remotely."),
        ("first-person Reflexion memory",
         "I proposed the wrong resolution; dispatch is required per the hardware fault diagnostics."),
        ("dispatch is required", "Dispatch a technician to fix the hardware fault."),
    ])

    result = reflexion(GOAL, llm, env, max_trials=3, memory_size=2)

    assert result.success
    assert len(result.trials) == 2  # trial 1 failed, trial 2 succeeded
    assert result.trials[0].feedback.success is False
    assert result.trials[1].feedback.success is True
    assert "dispatch is required" in result.memory[0]  # the real lesson was carried forward


def test_episodic_buffer_is_capped_at_memory_size(executor):
    """A persistently wrong actor (never learns) must still only ever carry
    the newest `memory_size` reflections, never more."""
    env = GroundedEnvironment(executor, OUTAGE_BUNDLE_WALTER_WHITE)
    always_wrong = ScriptedLLM(prose="Dispatch a technician right now.")  # always wrong for this bundle

    result = reflexion(GOAL, always_wrong, env, max_trials=4, memory_size=2)

    assert result.success is False
    assert len(result.trials) == 4
    assert len(result.memory) == 2  # capped, even though 4 trials ran
