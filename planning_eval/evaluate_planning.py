"""Planning-method evaluation across the whole lab.

Methods compared:

- PS / ToT / LATS(grounded) / LATS(ungrounded) on every case;
- decomposition-first vs dynamic decomposition on the grounded scenario
  bundles (the divergence case -- see planning/README.md);
- Self-Refine (PS draft + critique/revise) and Reflexion (episodic memory
  across trials) on the grounded scenario bundles.

Two case families:

- generic keyword cases -> scored by `NexlinkEnvironment` (ungrounded baseline);
- the real incident bundles from `planning_eval/scenarios.py` -> evaluated by
  `GroundedEnvironment`, which executes the proposal's write against the real
  DB + auth gate, so "success" means the write actually succeeded AND matched
  the expected resolution.

Every run records LLM calls, tokens, estimated cost (planning/cost.py), the
routing decision (planning/routing.py) and saves an `artifacts/run-*.json`
trace in the fork's save-artifact shape. Falls back to deterministic canned
decisions when GROQ_API_KEY is missing so the pipeline is testable offline.

Usage: `python planning_eval/evaluate_planning.py [METHOD[,METHOD...]]` --
optionally restrict to a subset (e.g. DECOMPOSITION_FIRST,DYNAMIC) to fit the
Groq free-tier rate budget.
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from planning import decompose_goal, dynamic_decomposition, execute_plan, final_output
from planning.cost import ThrottledLLM, TrackingLLM
from planning.mcp_tools import MCPToolExecutor
from planning.planning_lab.algorithms.environment import (
    EnvironmentFeedback,
    GroundedEnvironment,
    NexlinkEnvironment,
)
from planning.planning_lab.algorithms.lats import flatten_lats_tree, lats
from planning.planning_lab.algorithms.lats_ungrounded import lats_ungrounded
from planning.planning_lab.algorithms.plan_and_solve import plan_and_solve
from planning.planning_lab.algorithms.reflexion import reflexion
from planning.planning_lab.algorithms.self_refine import reflect_and_refine
from planning.planning_lab.algorithms.tree_of_thoughts import tree_of_thoughts
from planning.routing import route_subtask
from planning_eval.scenarios import credential_provider_for
from planning_eval.test_cases import GENERIC_CASES, SCENARIO_CASES

load_dotenv()

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

MAX_RETRIES = 2
RETRY_DELAY = 2.0
TOT_DEPTH = 1
TOT_BEAM_WIDTH = 2
LATS_ITERATIONS = 2
LATS_ACTIONS = 2


def create_llm():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("WARNING: GROQ_API_KEY not found in .env")
        return None
    tpm = int(os.getenv("GROQ_TPM", "6000"))
    return TrackingLLM(
        ThrottledLLM(
            ChatGroq(
                model_name="llama-3.1-8b-instant",
                groq_api_key=api_key,
                temperature=0.0,
                max_tokens=700,
            ),
            tpm=tpm,
        )
    )


def save_artifact(payload: dict) -> Path:
    ARTIFACT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACT_DIR / f"run-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run_with_retry(fn, label):
    last_exception = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:
            last_exception = exc
            if attempt >= MAX_RETRIES:
                break
            print(f"{label} failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            print(f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
    raise last_exception


def usage_for(llm, before, after=None):
    if llm is None:
        return {"calls": 0, "input_chars": 0, "output_chars": 0}
    after = after or llm.snapshot()
    return TrackingLLM.delta(before, after)


def result_dict(feedback, start, output, algorithm_name, usage):
    return {
        "algorithm": algorithm_name,
        "success": feedback.success,
        "score": feedback.score,
        "latency": round(time.time() - start, 4),
        "output": output[:200] + "..." if len(output) > 200 else output,
        "details": feedback.details,
        "calls": usage["calls"],
        "input_tokens": round(usage["input_chars"] / 4),
        "output_tokens": round(usage["output_chars"] / 4),
        "est_cost_usd": round(TrackingLLM.cost_for(usage), 6),
    }


def failure_result(start, details):
    return {
        "algorithm": "?",
        "success": False,
        "score": 0.0,
        "latency": round(time.time() - start, 4),
        "output": "",
        "details": details,
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "est_cost_usd": 0.0,
    }


# ---------------------------------------------------------------------------
# Generic (keyword) cases
# ---------------------------------------------------------------------------

def evaluate_generic(case, llm, method):
    start = time.time()
    before = llm.snapshot() if llm else None
    problem = case["problem"]
    keywords = case["expected_keywords"]
    env = NexlinkEnvironment(keywords)

    def scored(feedback, output, name):
        return result_dict(feedback, start, output, name, usage_for(llm, before))

    try:
        if method == "PLAN_AND_SOLVE":
            if llm is None:
                output = f"Diagnose the {problem} issue. Troubleshoot it and check equipment. Dispatch a technician if needed."
            else:
                output = run_with_retry(lambda: plan_and_solve(problem, llm), "PS")
            return scored(env.evaluate(output), output, "PS")

        if method == "TREE_OF_THOUGHTS":
            if llm is None:
                return failure_result(start, "ToT needs an LLM")
            thoughts = run_with_retry(
                lambda: tree_of_thoughts(problem, llm, depth=TOT_DEPTH, beam_width=TOT_BEAM_WIDTH),
                "Tree-of-Thoughts",
            )
            best_state, best_feedback = None, None
            for thought in thoughts:
                feedback = env.evaluate(thought.state)
                if best_feedback is None or feedback.score > best_feedback.score:
                    best_state, best_feedback = thought.state, feedback
            if best_state is None:
                return failure_result(start, "ToT produced no valid candidate.")
            return scored(best_feedback, best_state, "ToT")

        if method == "LATS":
            if llm is None:
                output = f"Diagnose the {problem} issue. Troubleshoot and dispatch a technician if needed."
                return scored(env.evaluate(output), output, "Grounded LATS")
            result = run_with_retry(
                lambda: lats(task=problem, llm=llm, environment=env, iterations=LATS_ITERATIONS, n_actions=LATS_ACTIONS),
                "Grounded LATS",
            )
            return scored(
                env.evaluate(result.output),
                result.output,
                "Grounded LATS",
            )

        if method == "LATS_UNGROUNDED":
            if llm is None:
                output = f"Diagnose the {problem} issue. Troubleshoot the problem."
                return scored(env.evaluate(output), output, "Ungrounded LATS")
            result = run_with_retry(
                lambda: lats_ungrounded(task=problem, llm=llm, iterations=LATS_ITERATIONS, n_actions=LATS_ACTIONS),
                "Ungrounded LATS",
            )
            return scored(env.evaluate(result.output), result.output, "Ungrounded LATS")
    except Exception as exc:
        return failure_result(start, f"{method} error: {exc}")

    return failure_result(start, f"Unknown method {method}")


# ---------------------------------------------------------------------------
# Grounded (real scenario) cases
# ---------------------------------------------------------------------------

def build_temp_db() -> str:
    workdir = tempfile.mkdtemp(prefix="nexlink-eval-")
    db_path = os.path.join(workdir, "nexlink.db")
    conn = sqlite3.connect(db_path)
    conn.executescript((Path(PROJECT_ROOT) / "db" / "schema.sql").read_text())
    conn.executescript((Path(PROJECT_ROOT) / "db" / "seed.sql").read_text())
    conn.commit()
    conn.close()
    return db_path


def compose_scenario_task(executor, case) -> str:
    bundle = case["bundle"]
    account_id = int(bundle["account_id"])
    reads = [
        executor.call("get_account_summary", {"account_id": account_id}),
        executor.call("get_equipment_diagnostics", {"account_id": account_id}),
        executor.call("list_support_tickets", {"account_id": account_id}),
    ]
    reads_text = "\n".join(f"- {item}" for item in reads)
    return (
        f"{bundle['staff_request']}\n\n"
        f"Real system state (fetched via MCP tools):\n{reads_text}\n\n"
        "Decide the resolution: dispatch a technician, remote fix (no dispatch), "
        "or apply a billing credit. State the decision clearly in your solution."
    )


def fresh_grounded(case):
    db_path = build_temp_db()
    os.environ["NEXLINK_DB_PATH"] = db_path
    executor = MCPToolExecutor(session_id=f"eval-{case['name'].replace(' ', '-')}")
    task = compose_scenario_task(executor, case)
    env = GroundedEnvironment(
        executor,
        case["bundle"],
        ticket_id=case.get("ticket_id"),
        credit_amount_usd=case.get("credit_amount_usd") or 30.0,
    )
    return task, env


def fallback_decision(case) -> str:
    expected = case["bundle"]["expected_resolution"]
    return {
        "dispatch_required": "Dispatch a technician to resolve the hardware fault.",
        "credit_applied": "Apply the billing credit to the account.",
        "no_dispatch_required": "No dispatch needed; resolve remotely.",
    }[expected]


class _FallbackLLM:
    """Offline stand-in for the real model, mirroring `tests/conftest.ScriptedLLM`:
    consumes scripted structured plans/decisions and answers reasoning nodes
    with canned prose. Keeps the offline eval fully deterministic.

    `prose` is returned by plain `invoke`; `plans`/`decisions` are consumed in
    order by `with_structured_output`. A "Reflexion memory" prompt (used by
    `reflexion`) returns `reflection` instead of `prose`.
    """

    def __init__(self, prose="", plans=None, decisions=None, reflection=None):
        self.prose = prose
        self.plans = list(plans or [])
        self.decisions = list(decisions or [])
        self.reflection = reflection or (
            "I decided without reading the diagnostic facts; "
            "next trial I will check the equipment log first."
        )
        self.prompts = []

    class _Structured:
        def __init__(self, owner, schema):
            self.owner = owner
            self.schema = schema

        def invoke(self, messages, **kwargs):
            self.owner.prompts.append(messages)
            name = self.schema.__name__
            if name == "GeneratedPlan":
                if not self.owner.plans:
                    raise RuntimeError("No scripted plan left for decompose_goal")
                return self.schema.model_validate(self.owner.plans.pop(0))
            if name == "DynamicDecision":
                if not self.owner.decisions:
                    raise RuntimeError("No scripted decision left for dynamic loop")
                return self.schema.model_validate(self.owner.decisions.pop(0))
            raise RuntimeError(f"Unsupported structured schema {name}")

    def with_structured_output(self, schema, *, method):
        return self._Structured(self, schema)

    def invoke(self, messages, **kwargs):
        self.prompts.append(messages)
        text = " ".join(str(m[1]) for m in messages)
        if "Reflexion memory" in text or "first-person Reflexion" in text:
            return SimpleNamespace(content=self.reflection)
        return SimpleNamespace(content=self.prose)


def _scripted_plan(case) -> dict:
    """The stale-DAG failure mode for the offline comparison: the planner reads
    diagnostics and then performs the resolution write WITHOUT a verification
    dependency, exactly like `static_plan_missing_verification` in the tests.
    On a fresh session the real auth gate rejects the write (SECURITY ERROR)."""
    account_id = int(case["bundle"]["account_id"])
    expected = case["bundle"]["expected_resolution"]
    tasks = [
        {"id": "diag", "instruction": "Fetch equipment diagnostics for the account",
         "depends_on": [], "kind": "tool",
         "tool": "get_equipment_diagnostics", "args": {"account_id": account_id}},
    ]
    if expected != "no_dispatch_required":
        write_tool = (
            "schedule_technician_dispatch"
            if expected == "dispatch_required"
            else "apply_billing_credit"
        )
        write_args = {"account_id": account_id}
        if write_tool == "schedule_technician_dispatch":
            write_args["description"] = "Resolve the hardware fault."
        else:
            write_args.update({
                "ticket_id": case.get("ticket_id"),
                "amount_usd": case.get("credit_amount_usd") or 30.0,
            })
        tasks.append({"id": "write", "instruction": "Perform the resolution write",
                      "depends_on": ["diag"], "kind": "tool",
                      "tool": write_tool, "args": write_args})
    tasks.append({"id": "summary", "instruction": "Conclude the resolution",
                  "depends_on": ["diag", "write"] if len(tasks) > 1 else ["diag"],
                  "kind": "synthesis"})
    return {"goal": "Resolve the incident", "tasks": tasks}


def _scripted_decisions(case) -> list:
    """The adaptive offline flow: the write is attempted first, hits the real
    SECURITY ERROR, then the planner verifies the session (staff PIN via the
    credential provider) and re-attempts the write -- `dynamic_flow_that_adapts`."""
    account_id = int(case["bundle"]["account_id"])
    expected = case["bundle"]["expected_resolution"]
    if expected == "no_dispatch_required":
        return [
            {"done": False, "tool": "get_equipment_diagnostics",
             "tool_args": {"account_id": account_id}},
            {"done": True},
        ]
    write_tool = (
        "schedule_technician_dispatch"
        if expected == "dispatch_required"
        else "apply_billing_credit"
    )
    write_args = {"account_id": account_id}
    if write_tool == "schedule_technician_dispatch":
        write_args["description"] = "Resolve the hardware fault."
    else:
        write_args.update({
            "ticket_id": case.get("ticket_id"),
            "amount_usd": case.get("credit_amount_usd") or 30.0,
        })
    return [
        {"done": False, "tool": "get_equipment_diagnostics",
         "tool_args": {"account_id": account_id}},
        {"done": False, "tool": write_tool, "tool_args": dict(write_args)},
        {"done": False, "tool": "verify_account_identity",
         "tool_args": {"account_id": account_id}},
        {"done": False, "tool": write_tool, "tool_args": dict(write_args)},
        {"done": True},
    ]


def _proposal_from_history(history) -> str:
    """Compose a resolution proposal from a dynamic-decomposition trace."""
    for label, result in history:
        if "SUCCESS" in result and "schedule_technician_dispatch" in label:
            return "Dispatch a technician to resolve the hardware fault."
        if "SUCCESS" in result and "apply_billing_credit" in label:
            return "Apply the billing credit to the account."
    return "No dispatch needed; resolve remotely."


def _plan_execution_feedback(env, plan, outputs) -> EnvironmentFeedback:
    """Score decomposition-first by what its OWN write did, not by what the
    scoring environment would do if it re-ran the write.

    `GroundedEnvironment.evaluate` always verifies and re-executes the write
    itself, so a stale DAG whose write hit `SECURITY ERROR` would otherwise
    score 1.0 just because the decision text was right. Here the incident is
    only resolved if the plan's write actually succeeded:

    - no write planned (remote fix)    -> score the final summary normally;
    - every planned write succeeded    -> score the final summary normally;
    - a planned write failed           -> correct decision, write failed = 0.5.
    """
    writes = [t for t in plan.tasks if t.kind == "tool" and t.tool in GroundedEnvironment.WRITE_TOOLS]
    if not writes or all(outputs[t.id].startswith("SUCCESS") for t in writes):
        return env.evaluate(final_output(plan, outputs))
    failed = next(outputs[t.id] for t in writes if not outputs[t.id].startswith("SUCCESS"))
    return EnvironmentFeedback(
        success=False,
        score=0.5,
        details=f"Correct decision but the plan's own write failed at runtime:\n{failed}",
    )


def _history_execution_feedback(env, history) -> EnvironmentFeedback:
    """Same principle for the dynamic-decomposition trace: resolved only when a
    write in the trace succeeded. If the loop tried and failed a write, that is
    "correct decision, write failed" = 0.5."""
    writes = [
        (label, result) for label, result in history
        if "schedule_technician_dispatch" in label or "apply_billing_credit" in label
    ]
    if not writes or any(result.startswith("SUCCESS") for _, result in writes):
        return env.evaluate(_proposal_from_history(history))
    failed = next(result for _, result in writes if not result.startswith("SUCCESS"))
    return EnvironmentFeedback(
        success=False,
        score=0.5,
        details=f"Correct decision but the plan's write failed at runtime:\n{failed}",
    )


def evaluate_grounded(case, llm, method):
    start = time.time()
    before = llm.snapshot() if llm else None
    task, env = fresh_grounded(case)

    def scored(feedback, output, name):
        return result_dict(feedback, start, output, name, usage_for(llm, before))

    try:
        if method == "PLAN_AND_SOLVE":
            if llm is None:
                output = fallback_decision(case)
            else:
                output = run_with_retry(lambda: plan_and_solve(task, llm), "PS")
            return scored(env.evaluate(output), output, "PS")

        if method == "TREE_OF_THOUGHTS":
            if llm is None:
                output = fallback_decision(case)
                return scored(env.evaluate(output), output, "ToT")
            thoughts = run_with_retry(
                lambda: tree_of_thoughts(task, llm, depth=TOT_DEPTH, beam_width=TOT_BEAM_WIDTH),
                "Tree-of-Thoughts",
            )
            best_state, best_feedback = None, None
            for thought in thoughts:
                feedback = env.evaluate(thought.state)
                if best_feedback is None or feedback.score > best_feedback.score:
                    best_state, best_feedback = thought.state, feedback
            if best_state is None:
                return failure_result(start, "ToT produced no valid candidate.")
            return scored(best_feedback, best_state, "ToT")

        if method == "LATS":
            if llm is None:
                output = fallback_decision(case)
                return scored(env.evaluate(output), output, "Grounded LATS")
            result = run_with_retry(
                lambda: lats(task=task, llm=llm, environment=env, iterations=LATS_ITERATIONS, n_actions=LATS_ACTIONS),
                "Grounded LATS",
            )
            feedback = env.evaluate(result.output)
            return scored(feedback, result.output, "Grounded LATS")

        if method == "LATS_UNGROUNDED":
            if llm is None:
                output = fallback_decision(case)
                return scored(env.evaluate(output), output, "Ungrounded LATS")
            result = run_with_retry(
                lambda: lats_ungrounded(task=task, llm=llm, iterations=LATS_ITERATIONS, n_actions=LATS_ACTIONS),
                "Ungrounded LATS",
            )
            return scored(env.evaluate(result.output), result.output, "Ungrounded LATS")

        if method == "DECOMPOSITION_FIRST":
            if llm is None:
                fake = _FallbackLLM(prose=fallback_decision(case), plans=[_scripted_plan(case)])
                plan = decompose_goal(task, fake)
                outputs = execute_plan(
                    plan, fake, executor=env.executor,
                    credential_provider=credential_provider_for(case["bundle"]),
                )
                output = final_output(plan, outputs)
            else:
                plan = run_with_retry(lambda: decompose_goal(task, llm), "Decomposition-first")
                outputs = run_with_retry(
                    lambda: execute_plan(
                        plan, llm, executor=env.executor,
                        credential_provider=credential_provider_for(case["bundle"]),
                    ),
                    "Decomposition-first",
                )
            output = final_output(plan, outputs)
            return scored(_plan_execution_feedback(env, plan, outputs), output, "Decomp-first")

        if method == "DYNAMIC":
            if llm is None:
                fake = _FallbackLLM(prose=fallback_decision(case), decisions=_scripted_decisions(case))
                history = dynamic_decomposition(
                    task, fake, executor=env.executor,
                    credential_provider=credential_provider_for(case["bundle"]),
                    max_steps=6,
                )
                output = _proposal_from_history(history)
            else:
                history = run_with_retry(
                    lambda: dynamic_decomposition(
                        task, llm, executor=env.executor,
                        credential_provider=credential_provider_for(case["bundle"]),
                        max_steps=8,
                    ),
                    "Dynamic decomposition",
                )
                output = _proposal_from_history(history)
            return scored(_history_execution_feedback(env, history), output, "Dynamic")

        if method == "SELF_REFINE":
            if llm is None:
                draft = fallback_decision(case)
                fake = _FallbackLLM(prose=draft)
                result = reflect_and_refine(task, draft, fake)
                output = result.revised
            else:
                draft = run_with_retry(lambda: plan_and_solve(task, llm), "PS")
                result = run_with_retry(lambda: reflect_and_refine(task, draft, llm), "Self-Refine")
                output = result.revised
            return scored(env.evaluate(output), output, "Self-Refine")

        if method == "REFLEXION":
            if llm is None:
                fake = _FallbackLLM(prose=fallback_decision(case))
                result = reflexion(task, fake, env, max_trials=3)
                output = result.output
            else:
                result = run_with_retry(
                    lambda: reflexion(task, llm, env, max_trials=3),
                    "Reflexion",
                )
                output = result.output
            return scored(env.evaluate(output), output, "Reflexion")
    except Exception as exc:
        return failure_result(start, f"{method} error: {exc}")

    return failure_result(start, f"Unknown method {method}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_result(name, result):
    print(
        f"{name} -> success={result['success']}, score={result['score']:.3f}, "
        f"latency={result['latency']}s, calls={result['calls']}, "
        f"in={result['input_tokens']}tok, out={result['output_tokens']}tok, "
        f"cost=${result['est_cost_usd']:.5f}"
    )
    if result.get("details"):
        print(f"  Details: {result['details'][:180]}..." if len(result['details']) > 180 else f"  Details: {result['details']}")


def print_summary(all_results, method_labels):
    print()
    print("=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    for name in method_labels.values():
        results = [item[name] for item in all_results if name in item]
        if not results:
            continue
        success_count = sum(1 for r in results if r["success"])
        average_score = sum(r["score"] for r in results) / len(results)
        average_latency = sum(r["latency"] for r in results) / len(results)
        total_calls = sum(r["calls"] for r in results)
        total_cost = sum(r["est_cost_usd"] for r in results)
        print()
        print(name)
        print(f"  Success: {success_count}/{len(results)}")
        print(f"  Success rate: {success_count / len(results):.2%}")
        print(f"  Average score: {average_score:.3f}")
        print(f"  Average latency: {average_latency:.3f}s")
        print(f"  Total LLM calls: {total_calls}")
        print(f"  Total est. cost: ${total_cost:.5f}")


def print_routing(all_results):
    print()
    print("=" * 80)
    print("ROUTING vs OUTCOME")
    print("=" * 80)
    for item in all_results:
        if "routing" not in item:
            continue
        routing = item["routing"]
        print(
            f"- {routing['case']}: routed {routing['method']} "
            f"({routing['reason']}) -> routed_success={routing['routed_success']}"
        )


def main():
    print("=" * 60)
    print("Nexlink Planning Evaluation")
    print("=" * 60)
    llm = create_llm()
    if llm is None:
        print("WARNING: Running in fallback mode (no API key)")
    all_results = []
    all_methods = [
        "PLAN_AND_SOLVE",
        "TREE_OF_THOUGHTS",
        "LATS",
        "LATS_UNGROUNDED",
        "DECOMPOSITION_FIRST",
        "DYNAMIC",
        "SELF_REFINE",
        "REFLEXION",
    ]
    requested = [m.strip().upper() for m in sys.argv[1:]] if len(sys.argv) > 1 else []
    methods = [m for m in all_methods if not requested or m in requested]
    generic_methods = [m for m in methods if m in all_methods[:4]]
    if requested and not generic_methods:
        print("NOTE: the selected methods only apply to the grounded scenario bundles; skipping generic cases")
    elif requested:
        print(f"NOTE: restricted to methods: {', '.join(methods)}")
    method_labels = {
        "PLAN_AND_SOLVE": "PS",
        "TREE_OF_THOUGHTS": "ToT",
        "LATS": "Grounded LATS",
        "LATS_UNGROUNDED": "Ungrounded LATS",
        "DECOMPOSITION_FIRST": "Decomp-first",
        "DYNAMIC": "Dynamic",
        "SELF_REFINE": "Self-Refine",
        "REFLEXION": "Reflexion",
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "requested_methods": requested,
        "runs": [],
    }

    if generic_methods:
        for case in GENERIC_CASES:
            print()
            print(f"Test case (keyword): {case['name']}")
            case_results = {}
            for method in generic_methods:
                result = evaluate_generic(case, llm, method)
                label = method_labels[method]
                case_results[label] = result
                print_result(label, result)
            all_results.append(case_results)
            payload["runs"].append({"family": "generic", "case": case["name"], "results": case_results})

    for case in SCENARIO_CASES:
        print()
        print(f"Test case (grounded): {case['name']}")
        print(f"  expected_resolution: {case['bundle']['expected_resolution']}")
        case_results = {}
        for method in methods:
            result = evaluate_grounded(case, llm, method)
            label = method_labels[method]
            case_results[label] = result
            print_result(label, result)
        shape = case.get("shape") or {"mostly_deterministic": True}
        routing = route_subtask(case["name"], **shape)
        routed_label = f"{method_labels[routing.method.name]} (routed)"
        routed_result = evaluate_grounded(case, llm, routing.method.name)
        case_results[routed_label] = routed_result
        case_results["routing"] = {
            "case": case["name"],
            "method": routed_label,
            "reason": routing.reason,
            "routed_success": routed_result["success"],
        }
        print(
            f"  routing -> {routed_label} ({routing.reason}); "
            f"routed_success={routed_result['success']}"
        )
        all_results.append(case_results)
        payload["runs"].append(
            {
                "family": "scenario",
                "case": case["name"],
                "expected_resolution": case["bundle"]["expected_resolution"],
                "shape": shape,
                "routing": case_results["routing"],
                "results": case_results,
            }
        )

    print_summary(all_results, method_labels)
    print_routing(all_results)
    artifact = save_artifact(payload)
    print()
    print("Evaluation complete.")
    print(f"Run artifact: {artifact}")
    print("=" * 60)


if __name__ == "__main__":
    main()
