"""Self-correction integration point. [Person 3 -- Integration concern]

`resolve_with_self_correction()` is the single function the live planning
agent (`agent/planning_agent.py`'s eventual `nextlink_planning` tool, or
`planning/planning_lab/cli.py`) should call once it has a proposed
resolution string and wants it checked and, if necessary, corrected before
anything gets written for real: it validates the proposal against the real
`GroundedEnvironment` (actual MCP handlers + database + auth gate, see
`environment.py`), and if that fails, escalates in two steps:

    1. One `reflect_and_refine()` pass -- cheap, correct whenever the
       proposal has exactly one thing wrong with it.
    2. If that still fails, a full `reflexion()` retry loop -- carries a
       capped episodic buffer of lessons across trials, which is what
       actually recovers a proposal with SEVERAL simultaneous problems
       (see `planning/tests/test_reflexion.py`'s multi-violation case).

This keeps the decision of *whether* self-correction is needed grounded in
the real system (not a guess), and keeps the two self-correction methods
composed the same way regardless of which caller invokes them -- the live
agent, the CLI, or `planning_eval`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

from .planning_lab.algorithms.environment import GroundedEnvironment
from .planning_lab.algorithms.reflexion import ReflexionResult, reflexion
from .planning_lab.algorithms.self_refine import ReflectionResult, reflect_and_refine


@dataclass
class SelfCorrectionResult:
    success: bool
    output: str
    method_used: str  # "none-needed" | "self-refine" | "reflexion" | "reflexion-exhausted"
    initial_feedback_details: str
    self_refine_result: Optional[ReflectionResult] = field(default=None)
    reflexion_result: Optional[ReflexionResult] = field(default=None)


def resolve_with_self_correction(
    goal: str,
    proposal: str,
    llm: BaseChatModel,
    environment: GroundedEnvironment,
    *,
    max_trials: int = 3,
    memory_size: int = 3,
) -> SelfCorrectionResult:
    """Validate `proposal` against `environment`; escalate to Self-Refine,
    then Reflexion, only as far as actually needed."""
    initial = environment.evaluate(proposal)
    if initial.success:
        return SelfCorrectionResult(True, proposal, "none-needed", initial.details)

    sr = reflect_and_refine(goal, proposal, llm, environment=environment)
    sr_feedback = environment.evaluate(sr.revised)
    if sr_feedback.success:
        return SelfCorrectionResult(True, sr.revised, "self-refine", initial.details, self_refine_result=sr)

    # One revision wasn't enough -- retry the whole proposal across trials,
    # carrying lessons (including what Self-Refine already learned) forward.
    task = f"{goal}\n\nRevise this proposal so it passes validation: {sr.revised}"
    rx = reflexion(task, llm, environment, max_trials=max_trials, memory_size=memory_size)
    method = "reflexion" if rx.success else "reflexion-exhausted"
    return SelfCorrectionResult(rx.success, rx.output, method, initial.details, sr, rx)
