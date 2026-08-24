"""Token-window pacer for Groq free-tier rate limits.

Groq's free tier allows ~8,000 tokens PER MINUTE per model (plus 200k/day).
Agentic flows fire several large LLM calls back-to-back, blowing the per-minute
cap mid-turn. This AsyncCallbackHandler sleeps *before* each model call just
enough to keep a sliding 60s window under the limit, so multi-step turns
(ticket creation, PIN verification) complete instead of 429-ing.

Usage:
    config = {"callbacks": [get_llm_pacer()]}
    await agent.ainvoke(payload, config=config)
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Optional

from langchain_core.callbacks import AsyncCallbackHandler


class TokenPacer(AsyncCallbackHandler):
    """Conservative sliding-window pacer (one entry per started LLM call)."""

    def __init__(
        self,
        tpm: int = 8000,
        est_tokens_per_call: int = 5000,
        window_s: float = 60.0,
        safety: float = 0.88,
        max_sleep_s: float = 50.0,
    ):
        self.tpm = tpm
        self.est = est_tokens_per_call
        self.window_s = window_s
        self.budget = tpm * safety
        self.max_sleep_s = max_sleep_s
        self._starts: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._starts and now - self._starts[0] >= self.window_s:
                    self._starts.popleft()
                projected = (len(self._starts) + 1) * self.est
                if projected <= self.budget:
                    self._starts.append(now)
                    return
                # Sleep until the oldest call leaves the window.
                wake_at = self._starts[0] + self.window_s
                await asyncio.sleep(min(max(0.05, wake_at - time.monotonic()),
                                        self.max_sleep_s))

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        await self.acquire()


_pacer: Optional[TokenPacer] = None


def init_pacer(tpm: int = 8000, est_tokens_per_call: int = 2200) -> TokenPacer:
    """Create/reuse the process-wide pacer (call once at agent build time).

    Groq's live rate-limit header confirms 8,000 tokens/minute on the free
    tier. At est=2200 three agent calls fit in the sliding window instead of
    two, cutting multi-step turns (PIN verify -> update -> answer) from
    minutes to roughly one window. Underestimating is safe: the chat
    backend's retry loop absorbs any resulting 429.
    """
    global _pacer
    if _pacer is None:
        _pacer = TokenPacer(tpm=tpm, est_tokens_per_call=est_tokens_per_call)
    return _pacer


def get_pacer() -> Optional[TokenPacer]:
    return _pacer
