"""Shared LLM chat-completion client factory.

OpenRouter and Groq expose the same ``chat.completions.create`` interface,
but their SDKs build request paths differently: the groq SDK hardcodes an
``openai/v1/`` path prefix, which 404s against OpenRouter. So:

* OpenRouter key set -> official OpenAI SDK pointed at OpenRouter.
* otherwise          -> groq SDK with its provider default.

Call sites only ever use ``client.chat.completions.create(...)``, which both
clients implement identically, so they stay untouched.
"""
from __future__ import annotations

from typing import Optional

from rag.config import RAGConfig


def make_llm_client(
    config: RAGConfig,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
):
    """Return a chat-completions client for the configured provider."""
    if base_url is None:
        base_url = config.api_base_url
    if api_key is None:
        api_key = config.groq_api_key

    if config.using_openrouter:
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base_url)

    import groq

    return groq.Groq(api_key=api_key, base_url=base_url)
