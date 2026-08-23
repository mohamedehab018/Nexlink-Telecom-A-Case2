"""Self-RAG-style verification gate.

Two explicit checks run before an answer reaches the user:

1. **Post-retrieval relevance** -- is each retrieved chunk actually relevant
   to the query, rather than trusting whatever the ANN/hybrid ranker handed
   back?
2. **Post-generation grounding** -- is the generated answer actually supported
   by the retrieved content?

The gate is applied uniformly to RAG contexts *and* to memories recalled from
the episodic/semantic stores: a recalled memory is just another ``(text,
metadata)`` document whose ``metadata["source_type"]`` may be ``"rag"``,
``"episodic"``, or ``"semantic"``.

Each check has an LLM-based critic (Groq, reflection-token style) and a
deterministic heuristic fallback so the system works without an API key.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from rag.config import RAGConfig
from rag.types import RetrievedDoc

# Self-RAG reflection-style tokens emitted by the LLM critic.
TOKEN_RELEVANT = "[Relevant]"
TOKEN_IRRELEVANT = "[Irrelevant]"
TOKEN_SUPPORTED = "[Fully supported]"
TOKEN_PARTIAL = "[Partially supported]"
TOKEN_UNSUPPORTED = "[No support]"


@dataclass
class RetrievalVerdict:
    relevant: bool
    score: float
    reason: str = ""
    source: str = "heuristic"


@dataclass
class GenerationVerdict:
    supported: bool
    level: str  # "supported" | "partial" | "unsupported"
    score: float
    reason: str = ""
    source: str = "heuristic"


@dataclass
class VerificationResult:
    query: str
    retrieval: List[RetrievalVerdict]
    generation: Optional[GenerationVerdict]
    passed: bool
    answer: str
    contexts: List[RetrievedDoc]
    latency: float = 0.0
    notes: List[str] = field(default_factory=list)


def _code_tokens(text: str) -> set:
    """Extract error codes, model names, numbers, and identifiers (lowercased)."""
    codes = {c.lower() for c in re.findall(r"\bERR-\d{4}\b", text, flags=re.IGNORECASE)}
    models = {m.lower() for m in re.findall(r"\bNextlink-\w+-V\d\b", text)}
    numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", text))
    words = set(re.findall(r"[a-z0-9]{4,}", text.lower()))
    return codes | models | numbers | words


class HeuristicRelevance:
    """Deterministic relevance score.

    Blends (a) coverage of *distinctive* identifiers -- error codes, hardware
    models, and numbers, the strongest evidence of topical match -- with
    (b) generic lexical overlap and (c) optional embedding similarity. The
    distinctive-term component dominates so that a chunk containing
    ``ERR-4091`` (or whose document model is the queried model) scores far
    above an unrelated policy paragraph.

    ``metadata`` is consulted for the document's ``model`` field, because
    tables inside a hardware spec sheet (LED references, power ranges) do not
    repeat the model name on every line yet are clearly about that model.
    """

    def __init__(self, embedder=None, threshold: float = 0.5) -> None:
        self._embedder = embedder
        self._threshold = threshold

    def score(self, query: str, text: str, metadata: Optional[Dict[str, object]] = None) -> float:
        q_tokens = _code_tokens(query)
        d_tokens = _code_tokens(text)
        if metadata:
            model = metadata.get("model")
            if model:
                d_tokens.add(str(model).lower())
        if not q_tokens:
            return 0.0
        overlap = q_tokens & d_tokens

        codes = {c.lower() for c in re.findall(r"\bERR-\d{4}\b", query, flags=re.IGNORECASE)}
        models = {m.lower() for m in re.findall(r"\bNextlink-\w+-V\d\b", query)}
        numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", query))
        distinctive = codes | models | numbers

        if distinctive:
            found = len(distinctive & d_tokens)
            lex = 0.6 * (found / len(distinctive)) + 0.4 * (len(overlap) / len(q_tokens))
        else:
            lex = len(overlap) / len(q_tokens)

        sim = 0.0
        if self._embedder is not None:
            q_vec = self._embedder.embed_query(query)
            d_vec = self._embedder.embed_query(text)
            sim = max(float(np.dot(q_vec, d_vec)), 0.0)
        return 0.5 * lex + 0.5 * sim


class GroqCritic:
    """LLM critic following the Self-RAG reflection-token format."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        from rag.config import load_config
        from rag.llm_client import make_llm_client

        self._client = make_llm_client(
            load_config(), api_key=api_key, base_url=base_url
        )
        self._model = model or "llama-3.3-70b-versatile"

    def _call(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict fact-checking critic. Judge relevance "
                        "and grounding and reply with the reflection tokens only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=24,
        )
        return (response.choices[0].message.content or "").strip()

    def relevance(self, query: str, doc: str) -> Tuple[str, str]:
        text = self._call(
            f"Query: {query}\n\nPassage: {doc}\n\n"
            "Is the passage relevant to answering the query? Reply with "
            f"{TOKEN_RELEVANT} or {TOKEN_IRRELEVANT} only."
        )
        if TOKEN_RELEVANT in text:
            return TOKEN_RELEVANT, text
        if TOKEN_IRRELEVANT in text:
            return TOKEN_IRRELEVANT, text
        return TOKEN_IRRELEVANT, text

    def support(self, query: str, answer: str, context: List[str]) -> Tuple[str, str]:
        ctx = "\n\n---\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(context))
        text = self._call(
            f"Query: {query}\n\nGenerated answer: {answer}\n\n"
            f"Retrieved context:\n{ctx}\n\n"
            "Is every claim in the answer directly supported by the context? "
            f"Reply with {TOKEN_SUPPORTED}, {TOKEN_PARTIAL}, or {TOKEN_UNSUPPORTED} only."
        )
        for token in (TOKEN_SUPPORTED, TOKEN_PARTIAL, TOKEN_UNSUPPORTED):
            if token in text:
                return token, text
        return TOKEN_PARTIAL, text


class SelfRAGVerifier:
    """Post-retrieval relevance + post-generation grounding gate.

    Usage::

        verifier = SelfRAGVerifier(config)
        result = verifier.verify(query, answer, docs)
        if not result.passed:
            # answer is blocked / must be revised
    """

    def __init__(self, config: RAGConfig, embedder=None, use_llm: Optional[bool] = None) -> None:
        self.config = config
        self._heuristic = HeuristicRelevance(embedder=embedder, threshold=config.relevance_score_threshold)
        use_llm = config.use_llm_critic if use_llm is None else use_llm
        self._critic: Optional[GroqCritic] = None
        if use_llm and config.groq_api_key:
            self._critic = GroqCritic(
                model=config.llm_model,
                api_key=config.groq_api_key,
                base_url=config.api_base_url,
            )
        self._source = "llm" if self._critic else "heuristic"

    # --- post-retrieval check ---

    def check_retrieval(self, query: str, docs: Sequence[RetrievedDoc]) -> List[RetrievalVerdict]:
        verdicts: List[RetrievalVerdict] = []
        for doc in docs:
            if self._critic is not None:
                token, raw = self._critic.relevance(query, doc.text)
                relevant = token == TOKEN_RELEVANT
                score = 1.0 if relevant else 0.0
                verdicts.append(
                    RetrievalVerdict(
                        relevant=relevant, score=score, reason=raw[:200], source="llm"
                    )
                )
            else:
                score = self._heuristic.score(query, doc.text, doc.metadata)
                relevant = score >= self.config.relevance_score_threshold
                verdicts.append(
                    RetrievalVerdict(
                        relevant=relevant,
                        score=round(score, 4),
                        reason=(
                            "lexical overlap above threshold"
                            if relevant
                            else "lexical overlap below threshold"
                        ),
                        source="heuristic",
                    )
                )
        return verdicts

    # --- post-generation check ---

    def check_generation(
        self, query: str, answer: str, docs: Sequence[RetrievedDoc]
    ) -> GenerationVerdict:
        context_texts = [d.text for d in docs]
        if self._critic is not None:
            token, raw = self._critic.support(query, answer, context_texts)
            level = {
                TOKEN_SUPPORTED: "supported",
                TOKEN_PARTIAL: "partial",
                TOKEN_UNSUPPORTED: "unsupported",
            }.get(token, "partial")
            supported = level == "supported"
            return GenerationVerdict(
                supported=supported, level=level, score=1.0 if supported else 0.0,
                reason=raw[:200], source="llm",
            )

        # Heuristic grounding: every distinctive claim in the answer (error
        # codes, model names, plan numbers) must appear in the context.
        context_blob = " ".join(context_texts).lower()
        answer_claims = _code_tokens(answer)
        answer_words = set(re.findall(r"[a-z0-9]{4,}", answer.lower()))
        if not answer_claims:
            return GenerationVerdict(
                supported=True, level="supported", score=1.0,
                reason="answer contains no verifiable claims",
                source="heuristic",
            )
        missing = answer_claims - _code_tokens(context_blob)
        coverage = 1.0 - (len(missing) / max(len(answer_claims), 1))
        if coverage >= 0.9:
            level, supported = "supported", True
        elif coverage >= 0.5:
            level, supported = "partial", False
        else:
            level, supported = "unsupported", False
        return GenerationVerdict(
            supported=supported,
            level=level,
            score=round(coverage, 4),
            reason=f"claims missing from context: {sorted(missing)[:6]}" if missing else "all claims grounded",
            source="heuristic",
        )

    # --- combined gate ---

    def verify(
        self,
        query: str,
        answer: str,
        docs: Sequence[RetrievedDoc],
        require_support: bool = True,
    ) -> VerificationResult:
        """Run both checks and produce a single gate decision.

        The gate passes only when at least one chunk is relevant AND the
        answer is fully supported. Otherwise it fails with the offending
        chunks / claims listed so the caller can re-retrieve or revise.
        """
        start = time.perf_counter()
        retrieval = self.check_retrieval(query, docs)
        relevant = [d for d, v in zip(docs, retrieval) if v.relevant]
        notes = []

        if not relevant:
            notes.append(
                f"post-retrieval check: none of {len(docs)} chunks relevant "
                f"(best score {max((v.score for v in retrieval), default=0.0):.2f})"
            )
            generation = self.check_generation(query, answer, [])
            passed = False
        else:
            generation = self.check_generation(query, answer, relevant)
            if generation.level == "partial":
                notes.append(
                    f"post-generation check: answer only partially grounded "
                    f"({generation.reason})"
                )
            elif generation.level == "unsupported":
                notes.append(
                    f"post-generation check: answer not grounded ({generation.reason})"
                )
            passed = generation.supported if require_support else bool(relevant)

        latency = time.perf_counter() - start
        return VerificationResult(
            query=query,
            retrieval=retrieval,
            generation=generation,
            passed=passed,
            answer=answer,
            contexts=list(docs),
            latency=latency,
            notes=notes,
        )

    def verify_rag(self, query: str, result: "RAGResult") -> VerificationResult:
        """Convenience: run the gate over a RAGResult."""
        return self.verify(query, result.answer, result.contexts)

    def verify_memory_recall(
        self, query: str, recalled: List[RetrievedDoc]
    ) -> VerificationResult:
        """Gate over episodic/semantic memory recalls.

        ``recalled`` items are plain ``RetrievedDoc`` objects whose metadata
        carries ``source_type`` ("episodic" / "semantic"); the same relevance
        and grounding checks apply, with an empty answer meaning the caller
        only wants the retrieval check.
        """
        return self.verify(query, "", recalled)
