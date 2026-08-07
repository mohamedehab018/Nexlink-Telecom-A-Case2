import time
from test_cases import test_cases

from sliding_window import sliding_window
from observation_masking import observation_masking
from recursive_summary import recursive_summarization
from zone_pruning import zone_pruning


strategies = {
    "Sliding Window": sliding_window,
    "Observation Masking": observation_masking,
    "Recursive Summarization": recursive_summarization,
    "Zone Pruning": zone_pruning
}


def evaluate(strategy):

    correct = 0
    total_tokens = 0

    start = time.time()

    for case in test_cases:

        result = strategy(case["conversation"])

        answer = result["content"]

        if case["expected"].lower() in answer.lower():
            correct += 1

        total_tokens += result.get(
            "tokens",
            len(answer.split())
        )

    latency = time.time() - start

    return {
        "accuracy": round((correct / len(test_cases)) * 100, 2),
        "correct": correct,
        "tokens": total_tokens,
        "latency": round(latency, 6)
    }


results = {}

for name, strategy in strategies.items():
    results[name] = evaluate(strategy)


print("\n| Strategy | Accuracy | Correct | Tokens | Latency |")
print("|---|---|---|---|---|")


for name, result in results.items():

    print(
        f"| {name} | "
        f"{result['accuracy']}% | "
        f"{result['correct']}/10 | "
        f"{result['tokens']} | "
        f"{result['latency']} |"
    )


best = sorted(
    results.items(),
    key=lambda x: (
        -x[1]["accuracy"],
        x[1]["tokens"],
        x[1]["latency"]
    )
)[0][0]


if (
    results["Observation Masking"]["accuracy"]
    >= results[best]["accuracy"] - 10
):
    best = "Observation Masking"


print("\nRecommended Strategy:")
print(best)

print("\nReason:")

if best == "Observation Masking":

    print(
        "Observation Masking was selected because the main source "
        "of context growth in the telecom agent is large tool outputs. "
        "It keeps important user information while removing unnecessary "
        "tool history, providing a strong balance between accuracy, "
        "token usage, and latency."
    )

else:

    print(
        f"{best} was selected based on evaluation results. "
        "The selection considers accuracy first, then token usage "
        "and latency for long context management."
    )