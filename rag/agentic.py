"""Agentic RAG: a multi-step retrieval loop built on LangGraph.

Unlike naive/hybrid search, the agentic pipeline does not assume the first
retrieval round is good enough. It:

1. **Decomposes** a complex query into sub-queries (LLM planner, heuristic
   fallback).
2. **Retrieves** for each sub-query (hybrid vector + BM25 search).
3. **Grades** the returned chunks for relevance (Self-RAG-style check).
4. **Decides** whether to re-query with a rewritten query or to generate.

The loop is implemented as a compiled LangGraph ``StateGraph``. A plain-Python
fallback with the identical node functions is used if ``langgraph`` is not
installed, so evaluation never depends on a specific graph runtime.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Dict, List, Optional

from rag.config import RAGConfig
from rag.generators import Generator, count_tokens
from rag.retrievers import HybridSearch
from rag.self_rag import HeuristicRelevance
from rag.types import RAGArchitecture, RAGResult, RetrievedDoc
from rag.vector_store import VectorStore

MODEL_RE = re.compile(r"\bNextlink-\w+-V\d\b")
CODE_RE = re.compile(r"\bERR-\d{4}\b")

_QUESTION_WORD_RE = re.compile(r"\b(what|how|which|does|do|why|should|can|is|are)\b", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"\b(?:ERR-\d{4}|Nextlink-\w+-V\d|\d+(?:\.\d+)?)\b", re.IGNORECASE)


def _self_contained(part: str) -> bool:
    """A sub-query is self-contained when it carries an explicit question or a
    distinctive identifier; otherwise it depends on anaphora (e.g. "what is
    its price?") and must not be queried in isolation."""
    return bool(_QUESTION_WORD_RE.search(part) or _IDENTIFIER_RE.search(part))


def heuristic_decompose(query: str) -> List[str]:
    """Split a query into sub-queries without an LLM.

    Splits on clause boundaries (``;``, ``.``, or ``and`` followed by a
    question word) and on multiple error-code mentions, but only when every
    resulting part is self-contained. A trailing fragment like "and what is
    its price?" resolves back to the main query and is dropped, since
    retrieving it in isolation only pulls noise.
    """
    parts = re.split(r"[;.]\s+(?=[A-Z])|\band\b\s+(?=what|how|which|does|do|why|should|can)\b", query, flags=re.IGNORECASE)
    parts = [p.strip().rstrip("?,").rstrip() + "?" for p in parts if p.strip()]
    if len(parts) > 1 and all(_self_contained(p) for p in parts):
        return parts

    codes = CODE_RE.findall(query)
    if len(codes) > 1:
        return [f"What does {code} mean and how is it fixed?" for code in codes]
    return [query]


def heuristic_rewrite(query: str, failed: List[str]) -> str:
    """Rewrite a query for another retrieval round by re-anchoring key terms."""
    tokens = CODE_RE.findall(query) + MODEL_RE.findall(query)
    for part in failed:
        tokens += CODE_RE.findall(part) + MODEL_RE.findall(part)
    unique = list(dict.fromkeys(tokens))
    if unique and all(t in query for t in unique):
        return query + " " + " ".join(unique)
    return query + " " + " ".join(unique) if unique else query


class QueryPlanner:
    """LLM query decomposition/rewrite with a deterministic fallback."""

    def __init__(self, config: RAGConfig) -> None:
        self._client = None
        if config.groq_api_key:
            try:
                import groq

                self._client = groq.Groq(api_key=config.groq_api_key)
                self._model = config.llm_model
            except Exception:
                self._client = None

    def decompose(self, query: str) -> List[str]:
        if self._client is None:
            return heuristic_decompose(query)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": "Break the question into independent sub-questions. "
                    "Return one sub-question per line with no numbering.",
                },
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=120,
        )
        lines = [ln.strip("-•1234567890. ").strip("?") + "?" for ln in (response.choices[0].message.content or "").splitlines() if ln.strip()]
        return lines or heuristic_decompose(query)

    def rewrite(self, query: str, failed: List[str]) -> str:
        if self._client is None:
            return heuristic_rewrite(query, failed)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": "Rewrite the query to retrieve missing information, "
                    "keeping exact error codes and model names intact. Output the "
                    "rewritten query only.",
                },
                {"role": "user", "content": f"Query: {query}\nMissing details: {'; '.join(failed)}"},
            ],
            temperature=0.0,
            max_tokens=120,
        )
        return (response.choices[0].message.content or query).strip() or query


class AgenticRAG(RAGArchitecture):
    """LangGraph multi-step retrieval loop."""

    name = "Agentic RAG (LangGraph)"

    def __init__(
        self,
        store: VectorStore,
        generator: Generator,
        config: RAGConfig,
        hybrid: Optional[HybridSearch] = None,
        planner: Optional[QueryPlanner] = None,
    ) -> None:
        self.store = store
        self.generator = generator
        self.config = config
        self.hybrid = hybrid or HybridSearch(store, generator, config)
        self.planner = planner or QueryPlanner(config)
        self._grader = HeuristicRelevance(embedder=store.embedder, threshold=config.relevance_threshold)

    # --- node implementations (shared by graph and fallback loop) ---

    def _node_decompose(self, state: Dict) -> Dict:
        sub_queries = self.planner.decompose(state["query"])
        state["sub_queries"] = sub_queries
        state["trace"].append(f"decompose -> {len(sub_queries)} sub-query(ies)")
        return state

    def _node_retrieve(self, state: Dict) -> Dict:
        seen = {c.metadata.get("point_id") for c in state["contexts"]}
        for sub in state["sub_queries"]:
            retrieved = self.hybrid.retrieve(
                sub, metadata_filter=state.get("metadata_filter"), k=self.config.top_k
            )
            for doc in retrieved:
                key = doc.metadata.get("point_id")
                if key not in seen:
                    setattr(doc, "_retrieval_query", sub)
                    state["contexts"].append(doc)
                    seen.add(key)
        state["rounds"] += 1
        state["trace"].append(
            f"retrieve round {state['rounds']}: {len(state['contexts'])} unique chunks"
        )
        return state

    def _node_grade(self, state: Dict) -> Dict:
        kept: List[RetrievedDoc] = []
        dropped = 0
        for doc in state["contexts"]:
            # Relevance is judged against the sub-query that retrieved the
            # chunk, not the full query: a chunk that answers "which error
            # code applies in arrears?" is relevant even though the full
            # scenario query does not mention the code.
            judge = getattr(doc, "_retrieval_query", state["query"])
            if self._grader.score(judge, doc.text, doc.metadata) >= self.config.relevance_threshold:
                kept.append(doc)
            else:
                dropped += 1
        state["contexts"] = kept
        state["dropped"] = state.get("dropped", 0) + dropped
        state["trace"].append(f"grade: kept {len(kept)}, dropped {dropped}")
        return state

    def _decide(self, state: Dict) -> str:
        # ``_node_grade`` already keeps only relevant chunks, so any surviving
        # chunk is admissible evidence. Re-query while the evidence is thin.
        contexts = state["contexts"]
        has_answer = len(contexts) >= max(2, self.config.top_k // 2)
        if not has_answer and state["rounds"] < self.config.max_retrieval_rounds:
            return "retrieve"
        return "generate"

    def _node_rewrite(self, state: Dict) -> Dict:
        rewritten = self.planner.rewrite(state["query"], state["sub_queries"])
        state["sub_queries"] = [rewritten]
        state["trace"].append(f"rewrite -> {rewritten[:80]}")
        return state

    def _node_generate(self, state: Dict) -> Dict:
        contexts = state["contexts"]
        if len(contexts) < 2:
            fallback = self.hybrid.retrieve(
                state["query"],
                metadata_filter=state.get("metadata_filter"),
                k=self.config.top_k,
            )
            if len(fallback) > len(contexts):
                contexts = fallback
                state["trace"].append(
                    "fallback: graded evidence thin -> raw hybrid top-k"
                )
        result = self.generator.generate(state["query"], [c.text for c in contexts])
        state["contexts"] = contexts
        state["answer"] = result.answer
        state["input_tokens"] += result.input_tokens
        state["output_tokens"] = result.output_tokens
        state["gen_latency"] = result.latency
        state["trace"].append(f"generate over {len(contexts)} contexts")
        return state

    # --- LangGraph graph ---

    def _build_graph(self):
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(dict)
        graph.add_node("decompose", self._node_decompose)
        graph.add_node("retrieve", self._node_retrieve)
        graph.add_node("grade", self._node_grade)
        graph.add_node("rewrite", self._node_rewrite)
        graph.add_node("generate", self._node_generate)
        graph.add_edge(START, "decompose")
        graph.add_edge("decompose", "retrieve")
        graph.add_edge("retrieve", "grade")
        graph.add_conditional_edges("grade", self._decide, {"retrieve": "rewrite", "generate": "generate"})
        graph.add_edge("rewrite", "retrieve")
        graph.add_edge("generate", END)
        return graph.compile()

    def answer(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, object]] = None,
    ) -> RAGResult:
        start = time.perf_counter()
        state: Dict = {
            "query": query,
            "metadata_filter": metadata_filter,
            "sub_queries": [],
            "contexts": [],
            "rounds": 0,
            "dropped": 0,
            "answer": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "gen_latency": 0.0,
            "trace": [],
        }
        try:
            graph = self._build_graph()
            final = graph.invoke(state)
        except ImportError:
            final = self._run_fallback(state)
        latency = time.perf_counter() - start

        return RAGResult(
            query=query,
            answer=final.get("answer", ""),
            contexts=final.get("contexts", []),
            input_tokens=int(final.get("input_tokens", 0)),
            output_tokens=int(final.get("output_tokens", 0)),
            latency=latency,
            retrieval_rounds=int(final.get("rounds", 1)),
            trace=final.get("trace", []),
        )

    def _run_fallback(self, state: Dict) -> Dict:
        """Plain-Python loop mirroring the compiled graph (no langgraph)."""
        self._node_decompose(state)
        while True:
            self._node_retrieve(state)
            self._node_grade(state)
            if self._decide(state) == "generate":
                break
            self._node_rewrite(state)
        self._node_generate(state)
        return state
