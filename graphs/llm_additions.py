"""Shared LLM plumbing for the state-graph technique additions.

Two of the four allowed LLM-call additions must live inside named nodes of
every state graph. The helpers here are deliberately tiny and fail-closed:

* ``llm_enabled()`` — techniques are on unless ``NEXLINK_GRAPH_LLM=0``
  (deterministic unit tests switch them off; demos run with them on).
* ``chat_json()`` — one chat completion, parsed as a JSON object. Any
  failure (no key, rate limit, malformed output) returns ``None`` so every
  calling node can fall back to its documented deterministic behaviour.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional


def llm_enabled() -> bool:
    return os.getenv("NEXLINK_GRAPH_LLM", "1") != "0"


def chat_json(system: str, user: str, max_tokens: int = 1500) -> Optional[dict[str, Any]]:
    """One completion constrained to a JSON object answer."""
    if not llm_enabled():
        return None

    def _attempt(model: str):
        from rag.config import load_config
        from rag.llm_client import make_llm_client

        cfg = load_config()
        client = make_llm_client(cfg)
        # The OpenAI SDK prefers max_completion_tokens (required by reasoning
        # models); the Groq SDK expects max_tokens.
        token_param = (
            "max_completion_tokens" if cfg.using_openrouter else "max_tokens"
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            **{token_param: max_tokens},
        )
        content = response.choices[0].message.content or ""
        # Reasoning models (qwen et al.) emit a <think> block first; strip it
        # so the JSON extraction sees only the final answer.
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        return json.loads(match.group(0)) if match else None

    try:
        from rag.config import load_config

        parsed = _attempt(load_config().llm_model)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # LLM_MODEL may belong to an inactive provider (e.g. an OpenRouter id
    # while GROQ_API_KEY is the active key). Retry with whichever model the
    # ACTIVE provider actually serves before giving up.
    try:
        fallback = (
            os.getenv("OPENROUTER_MODEL") or "openai/gpt-oss-120b"
            if (os.getenv("OPENROUTER_API_KEY"))
            else os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b"
        )
        parsed = _attempt(fallback)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        # Fail closed: callers fall back to their deterministic behaviour.
        return None
