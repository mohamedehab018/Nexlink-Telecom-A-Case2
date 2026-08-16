"""Generate `planning_eval/demo.md` -- a runnable demo transcript.

Every tool trace, score and decision below is produced by ACTUALLY running the
code in this repository offline (no API key): the MCP executor call logs are
real calls against a seeded copy of the real Nexlink database, and the scores
come from the real grounded environment (auth gate + DB writes). A tiny
scripted model stands in for Groq so the transcript is deterministic.

Regenerate with:  python planning_eval/run_demo.py
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from planning import decompose_goal, dynamic_decomposition, execute_plan, final_output
from planning.planning_lab.algorithms.environment import (
    GroundedEnvironment,
    NexlinkEnvironment,
)
from planning.planning_lab.algorithms.lats import lats
from planning.planning_lab.algorithms.lats_ungrounded import lats_ungrounded
from planning.planning_lab.algorithms.plan_and_solve import plan_and_solve
from planning.planning_lab.algorithms.reflexion import reflexion
from planning.planning_lab.algorithms.self_refine import reflect_and_refine
from planning.planning_lab.algorithms.tree_of_thoughts import tree_of_thoughts
from planning_eval.evaluate_planning import (
    _FallbackLLM,
    _scripted_decisions,
    _scripted_plan,
    fresh_grounded,
    fallback_decision,
)
from planning_eval.scenarios import credential_provider_for
from planning_eval.test_cases import SCENARIO_CASES

OUTAGE = SCENARIO_CASES[0]   # expected: no dispatch (remote fix)
DISPATCH = SCENARIO_CASES[1]  # expected: technician dispatch
CORRECT_DISPATCH = fallback_decision(DISPATCH)  # "Dispatch a technician ..."
CORRECT_REMOTE = fallback_decision(OUTAGE)      # "No dispatch needed; ..."

WRONG_REMOTE = "No dispatch needed; resolve the issue remotely."
WRONG_DISPATCH = "Diagnose the connection issue, then dispatch a technician to the customer site."


def truncate(text: str, width: int = 140) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[:width] + " ..."


class DemoLLM:
    """Deterministic stand-in for Groq during the demo. `attempt_prose` is used
    for the FIRST Reflexion attempt (so the transcript shows a failure and a
    memory), `prose` for every later generation call. JSON-only prompts
    (ToT / LATS value estimation) get canned JSON."""

    def __init__(self, prose, attempt_prose=None):
        self.prose = prose
        self.attempt_prose = attempt_prose or prose
        self.reflexion_attempts = 0
        self.prompts = []

    def invoke(self, messages, **kwargs):
        self.prompts.append(messages)
        text = " ".join(str(m[1]) for m in messages)
        if "Generate 3 distinct candidate next steps" in text:
            return SimpleNamespace(content=(
                '{"thoughts": ['
                '{"thought": "Diagnose the equipment log for hardware faults."},'
                '{"thought": "Troubleshoot the modem and line at the customer site."},'
                '{"thought": "Dispatch a technician to replace the faulty modem."}'
                "]}"
            ))
        if "Return ONLY valid JSON" in text:
            return SimpleNamespace(content='{"score": 0.85}')
        if "Produce the complete deliverable" in text:
            self.reflexion_attempts += 1
            if self.reflexion_attempts == 1:
                return SimpleNamespace(content=self.attempt_prose)
            return SimpleNamespace(content=self.prose)
        if "first-person Reflexion memory" in text:
            return SimpleNamespace(content=(
                "I chose a remote fix without confirming the equipment log was "
                "healthy; next trial I will schedule the technician dispatch."
            ))
        if "You are a separate critic" in text:
            return SimpleNamespace(content=(
                "The draft is too short to be actionable: it does not state the "
                "account, the hardware evidence, or the dispatch decision."
            ))
        if "Return only the improved deliverable" in text:
            return SimpleNamespace(content=self.prose)
        return SimpleNamespace(content=self.prose)


def build_temp_db():
    workdir = tempfile.mkdtemp(prefix="nexlink-demo-")
    db_path = os.path.join(workdir, "nexlink.db")
    conn = sqlite3.connect(db_path)
    conn.executescript((REPO_ROOT / "db" / "schema.sql").read_text())
    conn.executescript((REPO_ROOT / "db" / "seed.sql").read_text())
    conn.commit()
    conn.close()
    os.environ["NEXLINK_DB_PATH"] = db_path
    return db_path


def part_divergence():
    lines = []
    lines.append("## Part A — the divergence case: decomposition-first vs dynamic")
    lines.append("")
    lines.append("Same staff request (Ellen Ripley, dispatch bundle), same real database, two")
    lines.append("isolated sessions. The planner assumes the session was verified in a previous")
    lines.append("turn; a fresh session is not.")
    lines.append("")
    lines.append("**Staff request:**")
    lines.append(f"> {DISPATCH['bundle']['staff_request']}")
    lines.append("")
    lines.append("### A1. Decomposition-first (stale DAG)")
    build_temp_db()
    task, env = fresh_grounded(DISPATCH)
    fake = _FallbackLLM(prose=CORRECT_DISPATCH, plans=[_scripted_plan(DISPATCH)])
    plan = decompose_goal(task, fake)
    outputs = execute_plan(plan, fake, executor=env.executor,
                           credential_provider=credential_provider_for(DISPATCH["bundle"]))
    lines.append(f"`{len(plan.tasks)}`-node plan planned up front: {', '.join(t.id for t in plan.tasks)}")
    lines.append("")
    lines.append("Real tool trace (MCP executor call log):")
    for call in env.executor.call_log:
        lines.append(f"- `{call['tool']}({truncate(str(call['args']))})` -> `{truncate(call['result'])}`")
    write_out = outputs.get("write", "")
    resolved = write_out.startswith("SUCCESS")
    lines.append("")
    lines.append(f"Write node result: `{write_out}`")
    lines.append(f"**Incident resolved: {resolved}** -- the stale DAG executes its write without")
    lines.append("verification, the auth gate rejects it, and the rest of the plan runs anyway.")
    lines.append("")
    lines.append("### A2. Dynamic decomposition (adapts)")
    build_temp_db()
    task, env = fresh_grounded(DISPATCH)
    fake = _FallbackLLM(prose=CORRECT_DISPATCH, decisions=_scripted_decisions(DISPATCH))
    history = dynamic_decomposition(task, fake, executor=env.executor,
                                    credential_provider=credential_provider_for(DISPATCH["bundle"]),
                                    max_steps=6)
    lines.append("Real tool trace (MCP executor call log):")
    for call in env.executor.call_log:
        lines.append(f"- `{call['tool']}({truncate(str(call['args']))})` -> `{truncate(call['result'])}`")
    resolved = any("SUCCESS" in r and "schedule_technician_dispatch" in label
                   for label, r in history)
    lines.append("")
    lines.append("The planner observes the failed write, inserts `verify_account_identity`")
    lines.append("(staff PIN via the credential provider), and re-attempts the write.")
    lines.append(f"**Incident resolved: {resolved}.**")
    lines.append("")
    lines.append("Same decision, same tools, same database -- the difference is *when* the plan is")
    lines.append("committed. The trade (extra calls/tokens for the reshape) is measured in")
    lines.append("`tests/test_divergence.py` and in the comparison table.")
    return lines


def part_one_subtask_per_method():
    lines = []
    lines.append("## Part B — one sub-task solved by each planning method")
    lines.append("")
    lines.append("Shared sub-task: resolve the Ellen Ripley incident (hardware fault, dispatch needed),")
    lines.append("scored by the real grounded environment. Each method gets an isolated session.")
    lines.append("")
    rows = []

    def run(label, fn):
        build_temp_db()
        task, env = fresh_grounded(DISPATCH)
        output = fn(task, env)
        feedback = env.evaluate(output)
        rows.append((label, truncate(output, 110), feedback.score, feedback.success,
                     env.executor.call_count))

    llm = DemoLLM(prose=CORRECT_DISPATCH)
    run("Plan-and-Solve", lambda t, e: plan_and_solve(t, llm))
    run("Tree-of-Thoughts", lambda t, e: max(
        (n for n in tree_of_thoughts(t, llm, depth=1, beam_width=2)),
        key=lambda n: e.evaluate(n.state).score).state)
    run("LATS (grounded)", lambda t, e: lats(
        task=t, llm=llm, environment=e, iterations=1, n_actions=1).output)
    run("LATS (ungrounded)", lambda t, e: lats_ungrounded(
        task=t, llm=llm, iterations=1, n_actions=1).output)

    lines.append("| Method | Output (excerpt) | Grounded score | Success | Tool calls |")
    lines.append("| --- | --- | --- | --- | --- |")
    for label, output, score, success, tools in rows:
        lines.append(f"| {label} | `{output}` | {score:.1f} | {success} | {tools} |")
    lines.append("")
    lines.append("Grounded LATS pays a few extra tool calls because it generates and *evaluates*")
    lines.append("candidate actions against the real system before committing; Plan-and-Solve")
    lines.append("commits directly. Both resolve the incident here.")
    return lines


def part_self_refine():
    lines = []
    lines.append("## Part C — Self-Refine: a draft is critiqued and revised (grounded via GroundedEnvironment)")
    lines.append("")
    build_temp_db()
    task, env = fresh_grounded(DISPATCH)
    draft = WRONG_REMOTE  # short, unstructured, ignores the hardware evidence
    llm = DemoLLM(prose=CORRECT_DISPATCH)
    result = reflect_and_refine(task, draft, llm, environment=env)
    lines.append(f"Draft: `{draft}`")
    lines.append("")
    lines.append(f"External checks (source: {result.grounded_source} -- real MCP handlers + DB, not keywords):")
    for issue in result.grounded_issues:
        lines.append(f"- {issue}")
    lines.append("")
    lines.append(f"Independent critic: *{result.critique}*")
    lines.append("")
    lines.append(f"Revised: `{result.revised}`")
    lines.append("")
    feedback = env.evaluate(result.revised)
    lines.append(f"Grounded score of revised output: **{feedback.score:.1f} "
                 f"({'resolved' if feedback.success else 'not resolved'})** vs "
                 f"{env.evaluate(draft).score:.1f} for the unrevised draft.")
    return lines


def part_reflexion():
    lines = []
    lines.append("## Part D — Reflexion: learning across trials")
    lines.append("")
    build_temp_db()
    task, env = fresh_grounded(DISPATCH)
    llm = DemoLLM(prose=CORRECT_DISPATCH, attempt_prose=WRONG_REMOTE)
    result = reflexion(task, llm, env, max_trials=3)
    lines.append(f"Trials: {len(result.trials)}")
    lines.append("")
    for trial in result.trials:
        lines.append(f"- **Trial {trial.number}** attempt: `{trial.attempt}` -> "
                     f"score {trial.feedback.score:.1f} "
                     f"({'resolved' if trial.feedback.success else 'NOT resolved'})")
        if trial.reflection:
            lines.append(f"  - Reflection (episodic memory): {trial.reflection}")
    lines.append("")
    lines.append(f"Final: `{result.output}` -- success={result.success}")
    lines.append("")
    lines.append(f"Memory carried into the next trial: `{result.memory[-1]}`")
    lines.append("")
    lines.append("The wrong first decision (remote fix on a hardware fault) was rejected by the")
    lines.append("grounded environment; the stored lesson redirected the second attempt.")
    return lines


def part_grounded_vs_ungrounded():
    lines = []
    lines.append("## Part E — grounded beats keyword scoring: the $150 case")
    lines.append("")
    lines.append("The SAME proposal, scored two ways, on the Walter White outage bundle")
    lines.append("(diagnostics say the line is healthy -> no dispatch).")
    build_temp_db()
    task, env = fresh_grounded(OUTAGE)
    ungrounded = NexlinkEnvironment(["diagnose", "connection", "technician"]).evaluate(WRONG_DISPATCH)
    grounded = env.evaluate(WRONG_DISPATCH)
    lines.append(f"Proposal: `{WRONG_DISPATCH}`")
    lines.append("")
    lines.append(f"- **Ungrounded (`NexlinkEnvironment`)**: score **{ungrounded.score:.3f}** -> "
                 f"success={ungrounded.success}. It contains the words 'diagnose', 'connection' and")
    lines.append("  'technician', so the keyword check approves it.")
    lines.append(f"- **Grounded (`GroundedEnvironment`)**: score **{grounded.score:.1f}** -> "
                 f"success={grounded.success}. It actually schedules the technician dispatch")
    lines.append("  against the real DB -- an unnecessary ~$150 truck-roll for a healthy line.")
    lines.append("")
    lines.append(f"Details: {grounded.details.replace(chr(10), ' | ')}")
    return lines


def main():
    out = []
    out.append("# Nexlink planning agent -- demo transcript")
    out.append("")
    out.append("A live walkthrough of the planning lab: decomposition, the planning methods, self-")
    out.append("refinement, reflexion, and grounded feedback. Every line below was produced by")
    out.append("running this repository offline (no API key) against a seeded copy of the real")
    out.append("Nexlink database; the model is a deterministic stand-in for Groq.")
    out.append("")
    out.append("Reproduce: `python planning_eval/run_demo.py`  (regenerates this file).")
    out.append("")
    out.append("Scoring: `GroundedEnvironment` verifies the session and executes the proposal's")
    out.append("write through the real MCP handlers and auth gate (correct write = 1.0, correct")
    out.append("decision failed write = 0.5, wrong executed write = 0.3, wrong failed = 0.1).")
    out.append("")
    for part in (part_divergence, part_one_subtask_per_method,
                 part_self_refine, part_reflexion, part_grounded_vs_ungrounded):
        out.extend(part())
        out.append("")
        out.append("---")
        out.append("")

    target = Path(__file__).resolve().parent / "demo.md"
    target.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
