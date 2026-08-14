import os
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from planning.algorithms.planning_lab.algorithms.environment import NexlinkEnvironment
from planning.algorithms.planning_lab.algorithms.lats import lats

load_dotenv()


def create_llm():
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        print("ERROR: GROQ_API_KEY not found in .env")
        return None

    return ChatGroq(
        model_name="llama-3.1-8b-instant",
        groq_api_key=api_key,
        temperature=0.0,
        max_tokens=700,
    )


def test_lats():
    print("=" * 60)
    print("Testing Grounded LATS")
    print("=" * 60)

    llm = create_llm()

    if llm is None:
        print("Cannot test: No LLM available")
        return

    task = (
        "A customer reports that their internet connection is "
        "completely down. Explain the steps a support agent should "
        "take to diagnose the problem and decide whether a "
        "technician is needed."
    )

    expected_keywords = [
        "diagnose",
        "connection",
        "technician",
    ]

    print(f"\nTask: {task[:100]}...")
    print(f"Expected keywords: {expected_keywords}")
    print("\nRunning LATS...")

    environment = NexlinkEnvironment(
        expected_keywords
    )

    start = time.time()

    result = lats(
        task,
        llm,
        environment,
        iterations=1,
        n_actions=1,
    )

    elapsed = time.time() - start

    print("\n" + "=" * 60)
    print("LATS RESULT:")
    print("=" * 60)

    print(f"Success: {result.success}")
    print(f"Score: {result.best_score}")
    print(f"Iterations: {result.iterations}")
    print(f"Latency: {elapsed:.2f}s")

    print("\nOutput:")
    print("-" * 40)
    print(result.output[:1000])
    print("-" * 40)

    if result.output == "No LLM-generated candidate was produced.":
        print("\nLLM candidate was not generated.")
    else:
        print("\nLLM candidate was generated successfully.")

    feedback = environment.evaluate(
        result.output
    )

    print("\n" + "=" * 60)
    print("ENVIRONMENT EVALUATION:")
    print("=" * 60)

    print(f"Success: {feedback.success}")
    print(f"Score: {feedback.score}")
    print(f"Details: {feedback.details}")


def test_lats_multiple():
    print("=" * 60)
    print("Testing Grounded LATS with Multiple Tasks")
    print("=" * 60)

    llm = create_llm()

    if llm is None:
        print("Cannot test: No LLM available")
        return

    test_cases = [
        {
            "name": "Internet outage",
            "task": (
                "A customer reports that their internet connection "
                "is completely down. Explain the steps a support agent "
                "should take to diagnose the problem and decide whether "
                "a technician is needed."
            ),
            "keywords": [
                "diagnose",
                "connection",
                "technician",
            ],
        },
        {
            "name": "Slow connection",
            "task": (
                "A customer says their internet becomes very slow every "
                "evening. Create a step-by-step troubleshooting plan "
                "to identify the cause and resolve the issue."
            ),
            "keywords": [
                "diagnose",
                "speed",
                "troubleshooting",
            ],
        },
        {
            "name": "Router restart",
            "task": (
                "A customer's router keeps restarting randomly. Develop "
                "a plan to investigate the problem, check the equipment, "
                "and determine the appropriate next action."
            ),
            "keywords": [
                "router",
                "equipment",
                "diagnose",
            ],
        },
    ]

    results = []

    for case in test_cases:
        print(f"\nTest: {case['name']}")
        print("-" * 40)

        environment = NexlinkEnvironment(
            case["keywords"]
        )

        start = time.time()

        result = lats(
            case["task"],
            llm,
            environment,
            iterations=1,
            n_actions=1,
        )

        elapsed = time.time() - start

        no_candidate = (
            result.output
            == "No LLM-generated candidate was produced."
        )

        results.append(
            {
                "name": case["name"],
                "success": result.success,
                "score": result.best_score,
                "latency": elapsed,
                "no_candidate": no_candidate,
                "output_length": len(result.output),
            }
        )

        print(f"  Success: {result.success}")
        print(f"  Score: {result.best_score}")
        print(f"  Latency: {elapsed:.2f}s")
        print(f"  No candidate: {no_candidate}")
        print(
            f"  Output length: "
            f"{len(result.output)} chars"
        )

    print("\n" + "=" * 60)
    print("SUMMARY:")
    print("=" * 60)

    no_candidate_count = sum(
        1
        for result in results
        if result["no_candidate"]
    )

    success_count = sum(
        1
        for result in results
        if result["success"]
    )

    print(
        f"Total tests: "
        f"{len(results)}"
    )

    print(
        f"Successes: "
        f"{success_count}/{len(results)}"
    )

    print(
        f"No candidate: "
        f"{no_candidate_count}/{len(results)}"
    )

    if no_candidate_count == len(results):
        print(
            "\nLLM did not generate any candidates."
        )

    elif no_candidate_count == 0:
        print(
            "\nLATS generated candidates for all tests."
        )

    else:
        print(
            f"\n{no_candidate_count} tests "
            f"did not generate candidates."
        )


def test_llm_direct():
    print("=" * 60)
    print("Testing LLM Direct Generation")
    print("=" * 60)

    llm = create_llm()

    if llm is None:
        print("Cannot test: No LLM available")
        return

    task = (
        "A customer reports that their internet connection is "
        "completely down. Explain the steps a support agent should "
        "take to diagnose the problem and decide whether a "
        "technician is needed."
    )

    print(f"\nTask: {task[:100]}...")
    print("\nSending to LLM...")

    start = time.time()

    response = llm.invoke(
        [
            (
                "system",
                "You are a Nexlink support assistant. "
                "Provide a complete solution.",
            ),
            (
                "human",
                f"""
Task: {task}

Provide a complete solution with these steps:
1. Diagnose the problem
2. Troubleshoot the issue
3. Check equipment
4. Verify account
5. Escalate if needed

Include the words:
diagnose
troubleshooting
technician
dispatch
""",
            ),
        ]
    )

    elapsed = time.time() - start

    content = getattr(
        response,
        "content",
        "",
    )

    print(
        f"Latency: "
        f"{elapsed:.2f}s"
    )

    print(
        f"Output length: "
        f"{len(content)} chars"
    )

    print("\nOutput:")
    print("-" * 40)
    print(content[:1000])
    print("-" * 40)

    required = [
        "diagnose",
        "troubleshooting",
        "technician",
    ]

    found = [
        word
        for word in required
        if word in content.lower()
    ]

    missing = [
        word
        for word in required
        if word not in content.lower()
    ]

    print(
        f"\nRequired keywords found: "
        f"{found}"
    )

    print(
        f"Missing: "
        f"{missing if missing else 'None'}"
    )


if __name__ == "__main__":
    print("=" * 60)
    print("LATS TEST SUITE")
    print("=" * 60)

    test_lats()

    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)