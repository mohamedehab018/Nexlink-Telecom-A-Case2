"""Token and cost accounting for the planning-method evaluation.

The fork's cli.py saves JSON traces but never measures spend. The eval runs
wrap the real model in `TrackingLLM` so every run records LLM calls, prompt and
output characters, and an estimated cost for the chosen Groq model.
"""

from __future__ import annotations

from typing import Any, Dict, List

GROQ_MODEL = "llama-3.1-8b-instant"
PRICES_PER_1K_TOKENS = {"input_usd": 0.05, "output_usd": 0.08}
CHARS_PER_TOKEN = 4.0


def estimate_cost(input_chars: int, output_chars: int) -> float:
    """Rough USD estimate: tokens ~ chars / 4, priced per 1K tokens."""
    input_tokens = input_chars / CHARS_PER_TOKEN / 1000.0
    output_tokens = output_chars / CHARS_PER_TOKEN / 1000.0
    return (
        input_tokens * PRICES_PER_1K_TOKENS["input_usd"]
        + output_tokens * PRICES_PER_1K_TOKENS["output_usd"]
    )


class TrackingLLM:
    """Wraps a chat model and records every call's prompt/output sizes.

    The wrapped model keeps its own interface; the wrapper only intercepts
    `invoke` (the only method the planning methods call) and adds accounting.
    `snapshot()`/`delta()` let the eval attribute a slice of the total to one
    method run without restarting the session.
    """

    def __init__(self, llm: Any):
        self.llm = llm
        self.calls: List[Dict[str, int]] = []

    def invoke(self, messages, **kwargs):
        prompt_chars = sum(len(str(message[1])) for message in messages)
        response = self.llm.invoke(messages, **kwargs)
        content = getattr(response, "content", "")
        output_chars = len(content) if isinstance(content, str) else 0
        self.calls.append({"input_chars": prompt_chars, "output_chars": output_chars})
        return response

    def snapshot(self) -> Dict[str, int]:
        return {
            "calls": len(self.calls),
            "input_chars": sum(call["input_chars"] for call in self.calls),
            "output_chars": sum(call["output_chars"] for call in self.calls),
        }

    @staticmethod
    def delta(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
        return {key: after[key] - before[key] for key in before}

    @staticmethod
    def cost_for(usage: Dict[str, int]) -> float:
        return estimate_cost(usage["input_chars"], usage["output_chars"])
