"""Token and cost accounting for the planning-method evaluation.

The fork's cli.py saves JSON traces but never measures spend. The eval runs
wrap the real model in `TrackingLLM` so every run records LLM calls, prompt and
output characters, and an estimated cost for the chosen Groq model.
"""

from __future__ import annotations

import time
from collections import deque
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


class ThrottledLLM:
    """Paces calls to stay under a rolling per-minute token budget.

    Groq's free tier caps `llama-3.1-8b-instant` at 6000 TPM, so an evaluation
    that fires calls back-to-back gets 429 rate-limit errors. This wrapper
    estimates the incoming prompt's tokens with tiktoken's cl100k_base (Llama 3
    uses that tokenizer; chars/4 is the fallback), sleeps whenever the trailing
    window plus the new call would exceed the budget, and records the call's
    *real* token usage from the model response afterwards. Recording real usage
    is what keeps the window honest: markdown-heavy prompts cost ~3x the
    chars/4 guess, which is exactly why the naive estimate still 429'd.
    """

    def __init__(self, llm: Any, tpm: int = 6000, window: float = 55.0,
                 buffer_fraction: float = 0.8):
        self.llm = llm
        self.tpm = tpm
        self.window = window
        self.budget = tpm * buffer_fraction
        self._usage: deque = deque()
        self._encoder = None

    def _estimate_tokens(self, messages) -> float:
        try:
            if self._encoder is None:
                import tiktoken
                self._encoder = tiktoken.encoding_for_model("gpt-4")  # cl100k_base
            text = "\n".join(str(message[1]) for message in messages)
            return float(len(self._encoder.encode(text)))
        except Exception:
            return max(1.0, sum(len(str(message[1])) for message in messages) / CHARS_PER_TOKEN)

    @staticmethod
    def _real_tokens(response) -> float:
        usage_metadata = getattr(response, "usage_metadata", None)
        if isinstance(usage_metadata, dict):
            return usage_metadata.get("input_tokens", 0) + usage_metadata.get("output_tokens", 0)
        metadata = getattr(response, "response_metadata", None) or {}
        token_usage = metadata.get("token_usage")
        if isinstance(token_usage, dict):
            return token_usage.get("prompt_tokens", 0) + token_usage.get("completion_tokens", 0)
        return 0.0

    def _used(self) -> float:
        now = time.monotonic()
        while self._usage and now - self._usage[0][0] > self.window:
            self._usage.popleft()
        return sum(tokens for _, tokens in self._usage)

    def _wait(self, needed: float) -> None:
        if needed >= self.budget:
            return
        used = self._used()
        while used + needed > self.budget:
            overflow = used + needed - self.budget
            time.sleep(max(self.window * overflow / self.budget, 1.0))
            used = self._used()

    def _record(self, tokens: float) -> None:
        self._usage.append((time.monotonic(), tokens))

    def invoke(self, messages, **kwargs):
        needed = self._estimate_tokens(messages)
        self._wait(needed)
        before = self.llm.snapshot() if hasattr(self.llm, "snapshot") else None
        response = self.llm.invoke(messages, **kwargs)
        real = self._real_tokens(response)
        if real:
            self._record(real)
        else:
            output_chars = 0
            if before is not None:
                output_chars = TrackingLLM.delta(before, self.llm.snapshot())["output_chars"]
            else:
                content = getattr(response, "content", "")
                output_chars = len(content) if isinstance(content, str) else 0
            self._record(needed + output_chars / CHARS_PER_TOKEN)
        return response

    def with_structured_output(self, schema, **kwargs):
        if hasattr(self.llm, "with_structured_output"):
            return self.llm.with_structured_output(schema, **kwargs)
        raise NotImplementedError("Underlying LLM has no with_structured_output")

    def snapshot(self) -> Dict[str, int]:
        if hasattr(self.llm, "snapshot"):
            return self.llm.snapshot()
        raise NotImplementedError("Underlying LLM has no snapshot")
