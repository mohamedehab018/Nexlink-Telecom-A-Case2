"""Answer generators used by the retrieval pipelines.

* ``GroqGenerator`` -- real LLM generation through the Groq API (reads
  ``GROQ_API_KEY`` from the environment; never hardcoded).
* ``ExtractiveGenerator`` -- deterministic fallback that composes the answer
  strictly from the retrieved chunks (grounded by construction). Used by the
  evaluation suite so numbers are reproducible without an API key.

Both expose ``generate()`` returning a ``GenerationResult`` with token and
latency measurements.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

_TOKENIZER = None
_TOKENIZER_TRIED = False


def count_tokens(text: str) -> int:
    """Best-effort token count (tiktoken cl100k_base, else a char heuristic)."""
    global _TOKENIZER, _TOKENIZER_TRIED
    if not _TOKENIZER_TRIED:
        try:
            import tiktoken

            _TOKENIZER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _TOKENIZER = None
        _TOKENIZER_TRIED = True
    if _TOKENIZER is not None:
        return len(_TOKENIZER.encode(text or ""))
    return max(1, len(text or "") // 4)


@dataclass
class GenerationResult:
    answer: str
    input_tokens: int
    output_tokens: int
    latency: float
    raw: Optional[object] = field(default=None, metadata={"exclude": True})


@dataclass
class Generator(ABC):
    @abstractmethod
    def generate(
        self,
        query: str,
        context: List[str],
        system: Optional[str] = None,
    ) -> GenerationResult:
        ...


class GroqGenerator(Generator):
    """LLM generator using the Groq API (llama-3.3-70b-versatile by default)."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None) -> None:
        import groq

        self._model = model or "llama-3.3-70b-versatile"
        self._client = groq.Groq(api_key=api_key)

    def generate(
        self,
        query: str,
        context: List[str],
        system: Optional[str] = None,
    ) -> GenerationResult:
        system = system or (
            "You are a Nextlink ISP support engineer. Answer ONLY from the "
            "retrieved context provided. If the context does not contain the "
            "answer, say so. Cite the source document in your answer."
        )
        context_block = "\n\n---\n\n".join(
            f"[{i + 1}] {c}" for i, c in enumerate(context)
        )
        user_prompt = (
            f"QUESTION:\n{query}\n\nRETRIEVED CONTEXT:\n{context_block}\n\n"
            f"ANSWER (grounded only in the context above):"
        )
        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        latency = time.perf_counter() - start
        answer = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        if usage is not None:
            input_tokens = int(usage.prompt_tokens)
            output_tokens = int(usage.completion_tokens)
        else:
            input_tokens = count_tokens(system) + count_tokens(user_prompt)
            output_tokens = count_tokens(answer)
        return GenerationResult(
            answer=answer,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency=latency,
            raw=response,
        )


class ExtractiveGenerator(Generator):
    """Deterministic, offline generator.

    Builds the answer from the retrieved chunks by (1) dropping chunks that
    share no tokens with the query and (2) returning the top supporting
    sentences. The result is grounded by construction and token usage is
    measured, which keeps evaluation reproducible without an API key.
    """

    def __init__(self, max_sentences: int = 6) -> None:
        self._max_sentences = max_sentences

    @staticmethod
    def _tokens(text: str) -> set:
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    def generate(
        self,
        query: str,
        context: List[str],
        system: Optional[str] = None,
    ) -> GenerationResult:
        start = time.perf_counter()
        q_tokens = self._tokens(query)
        picked: List[str] = []
        for chunk in context:
            if not q_tokens:
                picked.append(chunk)
                continue
            chunk_tokens = self._tokens(chunk)
            overlap = len(q_tokens & chunk_tokens)
            if overlap >= 2:
                picked.append(chunk)
        answer = "\n\n".join(picked) if picked else "\n\n".join(context[:2])
        latency = time.perf_counter() - start
        return GenerationResult(
            answer=answer,
            input_tokens=count_tokens(query) + sum(count_tokens(c) for c in context),
            output_tokens=count_tokens(answer),
            latency=latency,
        )
