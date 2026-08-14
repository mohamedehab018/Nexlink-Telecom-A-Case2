"""Planning-method evaluation: PS / ToT / LATS(grounded) / LATS(ungrounded).

Two case families:

- generic keyword cases -> scored by `NexlinkEnvironment` (ungrounded baseline);
- the real incident bundles from `planning/scenarios.py` -> evaluated by
  `GroundedEnvironment`, which executes the proposal's write against the real
  DB + auth gate, so "success" means the write actually succeeded AND matched
  the expected resolution.

Every run records LLM calls, tokens, estimated cost (planning/cost.py), the
routing decision (planning/routing.py) and saves an `artifacts/run-*.json`
trace in the fork's save-artifact shape. Falls back to deterministic canned
decisions when GROQ_API_KEY is missing so the pipeline is testable offline.
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from planning.algorithms.planning_lab.algorithms.environment import (
    GroundedEnvironment,
    NexlinkEnvironment,
)
from planning.algorithms.planning_lab.algorithms.lats import flatten_lats_tree, lats
from planning.algorithms.planning_lab.algorithms.lats_ungrounded import lats_ungrounded
from planning.algorithms.planning_lab.algorithms.plan_and_solve import plan_and_solve
from planning.algorithms.planning_lab.algorithms.tree_of_thoughts import tree_of_thoughts
from planning.cost import TrackingLLM
from planning.mcp_tools import MCPToolExecutor
from planning.planning_test_cases import GENERIC_CASES, SCENARIO_CASES
from planning.routing import route_subtask

load_dotenv()

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

MAX_RETRIES = 2
RETRY_DELAY = 2.0
TOT_DEPTH = 2
TOT_BEAM_WIDTH = 2
LATS_ITERATIONS = 2
LATS_ACTIONS = 2


def create_llm():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("WARNING: GROQ_API_KEY not found in .env")
        return None
    return TrackingLLM(
        ChatGroq(
            model_name="llama-3.1-8b-instant",
            groq_api_key=api_key,
            temperature=0.0,
            max_tokens=700,
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


def print_summary(all_results):
    print()
    print("=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    algorithm_names = ["PS", "ToT", "Grounded LATS", "Ungrounded LATS"]
    for name in algorithm_names:
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
    methods = ["PLAN_AND_SOLVE", "TREE_OF_THOUGHTS", "LATS", "LATS_UNGROUNDED"]
    method_labels = {
        "PLAN_AND_SOLVE": "PS",
        "TREE_OF_THOUGHTS": "ToT",
        "LATS": "Grounded LATS",
        "LATS_UNGROUNDED": "Ungrounded LATS",
    }
    payload = {"model": "llama-3.1-8b-instant", "runs": []}

    for case in GENERIC_CASES:
        print()
        print(f"Test case (keyword): {case['name']}")
        case_results = {}
        for method in methods:
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
        routed_result = evaluate_grounded(case, llm, routing.method.name)
        case_results[routing.method.name] = routed_result
        case_results["routing"] = {
            "case": case["name"],
            "method": routing.method.name,
            "reason": routing.reason,
            "routed_success": routed_result["success"],
        }
        print(
            f"  routing -> {routing.method.name} ({routing.reason}); "
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

    print_summary(all_results)
    print_routing(all_results)
    artifact = save_artifact(payload)
    print()
    print("Evaluation complete.")
    print(f"Run artifact: {artifact}")
    print("=" * 60)


if __name__ == "__main__":
    main()
