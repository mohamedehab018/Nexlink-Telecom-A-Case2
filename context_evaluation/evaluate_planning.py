import os
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from context_evaluation.algorithms.plan_and_solve import plan_and_solve
from context_evaluation.algorithms.tree_of_thoughts import tree_of_thoughts, ThoughtNode
from context_evaluation.algorithms.lats import lats
from context_evaluation.algorithms.lats_ungrounded import lats_ungrounded
from context_evaluation.environment.nexlink_environment import NexlinkEnvironment

load_dotenv()

planning_test_cases = [
    {
        "name": "Internet outage",
        "problem": "A customer reports that their internet connection is completely down. Explain the steps a support agent should take to diagnose the problem and decide whether a technician is needed.",
        "expected_keywords": ["diagnose", "connection", "technician"],
    },
    {
        "name": "Slow connection",
        "problem": "A customer says their internet becomes very slow every evening. Create a step-by-step troubleshooting plan to identify the cause and resolve the issue.",
        "expected_keywords": ["diagnose", "speed", "troubleshooting"],
    },
    {
        "name": "Router restart",
        "problem": "A customer's router keeps restarting randomly. Develop a plan to investigate the problem, check the equipment, and determine the appropriate next action.",
        "expected_keywords": ["router", "equipment", "diagnose"],
    },
    {
        "name": "Red modem light",
        "problem": "A customer reports that the modem has a red status light and there is no internet connection. Provide a structured plan for diagnosing and resolving the issue.",
        "expected_keywords": ["modem", "diagnose", "connection"],
    },
    {
        "name": "WiFi authentication",
        "problem": "A customer changed their WiFi password and can no longer connect. Create a troubleshooting plan that identifies the likely cause and explains the steps to restore connectivity.",
        "expected_keywords": ["password", "wifi", "connect"],
    },
    {
        "name": "Billing problem",
        "problem": "A customer claims they were charged twice for their monthly internet subscription. Create a plan to investigate the billing records and determine the correct action.",
        "expected_keywords": ["billing", "charges", "account"],
    },
    {
        "name": "Plan upgrade",
        "problem": "A customer wants to change their current internet package to a faster plan. Explain the steps an agent should follow.",
        "expected_keywords": ["account", "plan", "upgrade"],
    },
    {
        "name": "Multiple devices",
        "problem": "A customer's connection becomes unstable whenever many devices are connected. Develop a diagnostic plan to identify the cause and recommend a solution.",
        "expected_keywords": ["devices", "connection", "diagnose"],
    },
    {
        "name": "Package expiration",
        "problem": "A customer says their internet package expired earlier than expected. Create a plan to investigate the subscription and determine what happened.",
        "expected_keywords": ["subscription", "account", "expiration"],
    },
    {
        "name": "Technician dispatch",
        "problem": "A customer has repeated connection failures and troubleshooting did not solve the issue. Create a plan that determines when a technician should be dispatched.",
        "expected_keywords": ["troubleshooting", "technician", "dispatch"],
    },
]

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
    return ChatGroq(
        model_name="llama-3.1-8b-instant",
        groq_api_key=api_key,
        temperature=0.0,
        max_tokens=700,
    )

def run_with_retry(function, label):
    last_exception = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return function()
        except Exception as exc:
            last_exception = exc
            if attempt >= MAX_RETRIES:
                break
            print(f"{label} failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            print(f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
    raise last_exception

def failure_result(start, details):
    return {
        "success": False,
        "score": 0.0,
        "latency": round(time.time() - start, 4),
        "output": "",
        "details": details,
    }

def evaluate_output(output, expected_keywords, start, algorithm_name):
    if not isinstance(output, str) or not output.strip():
        return failure_result(start, f"{algorithm_name} returned an empty response.")
    environment = NexlinkEnvironment(expected_keywords)
    feedback = environment.evaluate(output)
    return {
        "success": feedback.success,
        "score": feedback.score,
        "latency": round(time.time() - start, 4),
        "output": output[:200] + "..." if len(output) > 200 else output,
        "details": feedback.details,
    }

def evaluate_plan_and_solve(problem, llm, expected_keywords):
    start = time.time()
    try:
        if llm is None:
            output = f"Diagnose the {problem} issue by checking connection status. Troubleshoot by restarting equipment. If problem persists, dispatch a technician."
            return evaluate_output(output, expected_keywords, start, "PS")
        output = run_with_retry(lambda: plan_and_solve(problem, llm), "Plan-and-Solve")
        return evaluate_output(output, expected_keywords, start, "PS")
    except Exception as exc:
        return failure_result(start, f"PS error: {exc}")

def evaluate_tree_of_thoughts(problem, llm, expected_keywords):
    start = time.time()
    try:
        if llm is None:
            return failure_result(start, "No LLM available")
        thoughts = run_with_retry(
            lambda: tree_of_thoughts(problem, llm, depth=TOT_DEPTH, beam_width=TOT_BEAM_WIDTH),
            "Tree-of-Thoughts"
        )
        if not thoughts:
            return failure_result(start, "Tree-of-Thoughts returned no candidate.")
        environment = NexlinkEnvironment(expected_keywords)
        best_node = None
        best_feedback = None
        for thought in thoughts:
            state = thought.state if hasattr(thought, 'state') else str(thought)
            if not isinstance(state, str) or not state.strip():
                continue
            feedback = environment.evaluate(state)
            if best_feedback is None or feedback.score > best_feedback.score:
                best_node = thought
                best_feedback = feedback
            if feedback.success:
                break
        if best_node is None or best_feedback is None:
            return failure_result(start, "Tree-of-Thoughts produced no valid candidate.")
        return {
            "success": best_feedback.success,
            "score": best_feedback.score,
            "latency": round(time.time() - start, 4),
            "output": best_node.state[:200] + "..." if hasattr(best_node, 'state') and len(best_node.state) > 200 else str(best_node)[:200],
            "details": best_feedback.details,
        }
    except Exception as exc:
        return failure_result(start, f"ToT error: {exc}")

def evaluate_lats(problem, llm, expected_keywords):
    start = time.time()
    try:
        environment = NexlinkEnvironment(expected_keywords)
        if llm is None:
            output = f"Diagnose the {problem} issue. Troubleshoot the problem. Escalate if needed."
            return evaluate_output(output, expected_keywords, start, "Grounded LATS")
        result = run_with_retry(
            lambda: lats(task=problem, llm=llm, environment=environment, iterations=LATS_ITERATIONS, n_actions=LATS_ACTIONS),
            "Grounded LATS"
        )
        output = result.output if hasattr(result, "output") else ""
        if not isinstance(output, str) or not output.strip():
            return failure_result(start, "Grounded LATS returned an empty response.")
        return {
            "success": result.success if hasattr(result, "success") else False,
            "score": result.best_score if hasattr(result, "best_score") else 0.0,
            "latency": round(time.time() - start, 4),
            "output": output[:200] + "..." if len(output) > 200 else output,
            "details": f"LATS iterations: {result.iterations if hasattr(result, 'iterations') else 0}",
        }
    except Exception as exc:
        return failure_result(start, f"LATS error: {exc}")

def evaluate_lats_ungrounded(problem, llm, expected_keywords):
    start = time.time()
    try:
        if llm is None:
            output = f"Diagnose the {problem} issue. Troubleshoot the problem."
            return evaluate_output(output, expected_keywords, start, "Ungrounded LATS")
        result = run_with_retry(
            lambda: lats_ungrounded(task=problem, llm=llm, iterations=LATS_ITERATIONS, n_actions=LATS_ACTIONS),
            "Ungrounded LATS"
        )
        output = result.output if hasattr(result, "output") else ""
        return evaluate_output(output, expected_keywords, start, "Ungrounded LATS")
    except Exception as exc:
        return failure_result(start, f"Ungrounded LATS error: {exc}")

def print_result(name, result):
    print(f"{name} -> success={result['success']}, score={result['score']:.3f}, latency={result['latency']}s")
    if result.get("details"):
        print(f"Details: {result['details']}")

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
        success_count = sum(1 for result in results if result["success"])
        average_score = sum(result["score"] for result in results) / len(results)
        average_latency = sum(result["latency"] for result in results) / len(results)
        print()
        print(name)
        print(f"  Success: {success_count}/{len(results)}")
        print(f"  Success rate: {success_count / len(results):.2%}")
        print(f"  Average score: {average_score:.3f}")
        print(f"  Average latency: {average_latency:.3f}s")

def main():
    print("=" * 60)
    print("Nexlink Planning Evaluation")
    print("=" * 60)
    llm = create_llm()
    if llm is None:
        print("WARNING: Running in fallback mode (no API key)")
    all_results = []
    for case in planning_test_cases:
        print()
        print(f"Test case: {case['name']}")
        print(f"Problem: {case['problem'][:100]}...")
        case_results = {}
        print("\nRunning Plan-and-Solve...")
        ps = evaluate_plan_and_solve(case["problem"], llm, case["expected_keywords"])
        case_results["PS"] = ps
        print_result("PS", ps)
        print("\nRunning Tree-of-Thoughts...")
        tot = evaluate_tree_of_thoughts(case["problem"], llm, case["expected_keywords"])
        case_results["ToT"] = tot
        print_result("ToT", tot)
        print("\nRunning Grounded LATS...")
        grounded = evaluate_lats(case["problem"], llm, case["expected_keywords"])
        case_results["Grounded LATS"] = grounded
        print_result("Grounded LATS", grounded)
        print("\nRunning Ungrounded LATS...")
        ungrounded = evaluate_lats_ungrounded(case["problem"], llm, case["expected_keywords"])
        case_results["Ungrounded LATS"] = ungrounded
        print_result("Ungrounded LATS", ungrounded)
        all_results.append(case_results)
        print("-" * 60)
    print_summary(all_results)
    print()
    print("Evaluation complete.")
    print("=" * 60)

if __name__ == "__main__":
    main()