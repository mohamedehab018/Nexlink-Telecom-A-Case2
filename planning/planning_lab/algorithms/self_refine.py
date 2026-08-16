"""Self-Refine. [Person 3 -- Self-correction concern, scope: one draft]

`deterministic_checks()` is the toolkit's original generic heuristic
(word count / goal-term overlap / visible structure) -- kept unchanged so
`reflect_and_refine()` still works exactly as before for any non-Nexlink
caller. It is NOT grounded in anything real: it cannot tell whether an
account exists, whether a ticket is actually open, or whether a proposed
dispatch would be redundant.

`reflect_and_refine()` now accepts an optional `environment` (a
`planning.planning_lab.algorithms.environment.GroundedEnvironment`, built on
the real `MCPToolExecutor` -- see `environment.py`). When one is supplied,
its `EnvironmentFeedback.details` -- produced by actually executing the
proposal through the real MCP handlers, database and auth gate -- replaces
`deterministic_checks()`'s generic output as the "External checks" fed to
the critic and reviser. This is the adaptation the lab requires explicitly:
"for every critique step in your system ... state explicitly what the
source of truth is."

`critic` lets the judging call use a DIFFERENT model than the one that
drafts the revision, so `planning_eval` can test whether an independent
critic changes the evaluation, per the brief -- defaults to `llm` when not
given.
"""
import re
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel


def deterministic_checks(goal: str, draft: str) -> list[str]:
    """Unchanged from the toolkit. Used only as the fallback when no
    `environment` is passed to `reflect_and_refine()`."""
    issues: list[str] = []
    if len(draft.split()) < 80:
        issues.append("The deliverable is under 80 words and is probably incomplete.")
    goal_terms = {
        word.lower()
        for word in re.findall(r"[A-Za-z]{5,}", goal)
        if word.lower() not in {"create", "design", "write", "build", "about", "using"}
    }
    represented = [term for term in goal_terms if term in draft.lower()]
    if goal_terms and not represented:
        issues.append("The output contains none of the goal's significant terms.")
    if not re.search(r"(^|\n)(#{1,3}\s+|\d+[.)]\s+|[-*]\s+)", draft):
        issues.append("The deliverable has no visible structure (headings or list items).")
    return issues


@dataclass
class ReflectionResult:
    draft: str
    critique: str
    revised: str
    grounded_issues: list[str]
    grounded_source: str  # e.g. "grounded:GroundedEnvironment" or "ungrounded:deterministic_checks"


def reflect_and_refine(
    goal: str,
    draft: str,
    llm: BaseChatModel,
    environment=None,
    critic: BaseChatModel | None = None,
) -> ReflectionResult:
    critic = critic or llm

    if environment is not None:
        feedback = environment.evaluate(draft)
        if feedback.success:
            # `feedback.details` is a trace log (decision/expected/write result),
            # always populated -- it is only "issues" to report when the
            # grounded check actually failed.
            grounded: list[str] = []
        else:
            details = feedback.details
            grounded = details.split("\n") if isinstance(details, str) else list(details)
        grounded_source = f"grounded:{type(environment).__name__}"
    else:
        grounded = deterministic_checks(goal, draft)
        grounded_source = "ungrounded:deterministic_checks"
    grounded_report = "\n".join(f"- {issue}" for issue in grounded) or "- External checks passed."

    critique_response = critic.invoke([
        ("system", "You are a separate critic. Judge against the rubric; do not rewrite the draft."),
        ("human", f"""Goal: {goal}
Rubric: correctness, completeness, internal consistency, and instruction adherence.
External checks (source: {grounded_source}):
{grounded_report}

Draft:
{draft}

List concrete issues. If there are none, respond exactly PASS."""),
    ], temperature=0.2)
    critique_text = critique_response.content
    if not isinstance(critique_text, str) or not critique_text.strip():
        raise RuntimeError("The chat model returned an empty or unsupported response")
    critique_text = critique_text.strip()

    if critique_text.strip().upper() == "PASS" and not grounded:
        revised = draft
    else:
        response = llm.invoke([
            ("system", "Revise a deliverable using both external checks and an independent critique. "
                        "Every issue in the external checks MUST be resolved; it is not optional feedback."),
            ("human", f"Goal: {goal}\n\nDraft:\n{draft}\n\nExternal checks (source: {grounded_source}):\n"
                       f"{grounded_report}\n\nCritique:\n{critique_text}\n\nReturn only the improved deliverable."),
        ], temperature=0.2)
        revised = response.content
        if not isinstance(revised, str) or not revised.strip():
            raise RuntimeError("The chat model returned an empty or unsupported response")
        revised = revised.strip()
    return ReflectionResult(draft, critique_text, revised, grounded, grounded_source)


def ungrounded_critique(draft: str, llm: BaseChatModel) -> str:
    """The deliberate ungrounded baseline the lab asks for: the SAME model
    judging the SAME draft with NO database access and no grounded report in
    its prompt at all. Used only for the grounded-vs-ungrounded comparison
    (see `planning/tests/test_self_refine.py`); never used inside
    `reflect_and_refine()` above.
    """
    response = llm.invoke([
        ("system", "You review a proposed resolution's wording only -- you have no database access "
                    "and cannot verify any fact in it."),
        ("human", f"Proposal:\n{draft}\n\nIs this clear and complete? Reply PASS or a one-line concern."),
    ], temperature=0.2)
    content = response.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("The chat model returned an empty or unsupported response")
    return content.strip()
