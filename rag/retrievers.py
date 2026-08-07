"""Naive RAG and hybrid (vector + BM25 with Reciprocal Rank Fusion) retrieval.

Both architectures share a common ``RAGArchitecture`` interface so the
evaluation suite can benchmark them identically.

* **Naive RAG** -- embed the query, run a single HNSW similarity search, and
  generate from the top chunks.
* **Hybrid search** -- run vector similarity and BM25 keyword search in
  parallel, fuse the two ranked lists with Reciprocal Rank Fusion, then
  generate from the fused top chunks.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from rag.config import RAGConfig
from rag.generators import Generator
from rag.text_utils import content_tokens, distinctive_terms, tokenize
from rag.types import RAGArchitecture, RAGResult, RetrievedDoc
from rag.vector_store import VectorStore, matches_metadata


class BM25Index:
    """BM25 keyword retriever over the indexed corpus.

    Backed by ``rank_bm25`` when available; otherwise a compatible in-module
    implementation is used so the pipeline never hard-depends on it.

    Exact-identifier bonus: documents containing the query's error codes,
    hardware models, or numbers receive a flat score bonus. Citation-heavy
    queries ("what does ERR-4091 mean") are driven by the identifier, so the
    section that actually defines the code ranks above documents that merely
    reuse generic vocabulary.
    """

    IDENTIFIER_BONUS = 8.0

    def __init__(self, documents: List[str]) -> None:
        self._documents = documents
        tokenized = [tokenize(d) for d in documents]
        try:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi(tokenized)
        except ImportError:
            self._bm25 = _FallbackBM25(tokenized)

    def _identifier_terms(self, query: str) -> set:
        return distinctive_terms(query)

    def search(self, query: str, limit: int = 4) -> List[tuple]:
        """Return the top-``limit`` ranked (corpus_index, score) pairs."""
        scores = list(self._bm25.get_scores(content_tokens(query)))
        identifiers = self._identifier_terms(query)
        if identifiers:
            lowered = [d.lower() for d in self._documents]
            for i, doc in enumerate(lowered):
                if any(ident in doc for ident in identifiers):
                    scores[i] += self.IDENTIFIER_BONUS
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [(i, float(scores[i])) for i in order[:limit]]


class _FallbackBM25:
    """Minimal Okapi BM25 (no external dependency)."""

    def __init__(self, corpus: List[List[str]]) -> None:
        self.corpus = corpus
        self.avgdl = sum(len(d) for d in corpus) / max(len(corpus), 1)
        self.df: Dict[str, int] = {}
        for doc in corpus:
            for term in set(doc):
                self.df[term] = self.df.get(term, 0) + 1
        self.N = len(corpus)

    def _idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        return max(0.0, ((self.N - n + 0.5) / (n + 0.5) + 1.0) ** 0.5)

    def get_scores(self, query: List[str]) -> List[float]:
        k1, b = 1.5, 0.75
        scores = []
        for doc in self.corpus:
            dl = len(doc)
            tf_counts = {}
            for term in doc:
                tf_counts[term] = tf_counts.get(term, 0) + 1
            score = 0.0
            for term in set(query):
                tf = tf_counts.get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf(term)
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / self.avgdl))
            scores.append(score)
        return scores


def reciprocal_rank_fusion(
    ranked_lists: List[List[str]],
    k: int = 60,
    top_n: int = 4,
) -> List[Dict[str, float]]:
    """Fuse ranked lists of doc ids using Reciprocal Rank Fusion (RRF)."""
    fused: Dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)
    return [{"id": doc_id, "score": score} for doc_id, score in ordered[:top_n]]


class NaiveRAG(RAGArchitecture):
    """Baseline pipeline: single ANN search -> generation."""

    name = "Naive RAG"

    def __init__(
        self,
        store: VectorStore,
        generator: Generator,
        config: RAGConfig,
    ) -> None:
        self.store = store
        self.generator = generator
        self.config = config

    def answer(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, object]] = None,
    ) -> RAGResult:
        start = time.perf_counter()
        query_vec = self.store.embedder.embed_query(query)
        hits = self.store.search(query_vec, limit=self.config.top_k, metadata_filter=metadata_filter)
        contexts = [
            RetrievedDoc(text=h["text"], metadata=h["metadata"], score=h["score"], rank=i)
            for i, h in enumerate(hits)
        ]
        result = self.generator.generate(query, [c.text for c in contexts])
        latency = time.perf_counter() - start + result.latency
        return RAGResult(
            query=query,
            answer=result.answer,
            contexts=contexts,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency=latency,
            retrieval_rounds=1,
            trace=[f"naive: vector top-{len(contexts)}"],
        )


class HybridSearch(RAGArchitecture):
    """Vector + BM25 search fused with Reciprocal Rank Fusion."""

    name = "Hybrid search (vector + BM25)"

    def __init__(
        self,
        store: VectorStore,
        generator: Generator,
        config: RAGConfig,
    ) -> None:
        self.store = store
        self.generator = generator
        self.config = config
        self._bm25: Optional[BM25Index] = None
        self._bm25_docs: List[str] = []
        self._bm25_ids: List[str] = []

    def _ensure_bm25(self) -> None:
        if self._bm25 is not None:
            return
        all_docs = self.store.get_all()
        self._bm25_docs = [d["text"] for d in all_docs]
        self._bm25_ids = [str(d["id"]) for d in all_docs]
        self._bm25 = BM25Index(self._bm25_docs)

    def _bm25_results(
        self, query: str, limit: int
    ) -> List[Dict[str, float]]:
        self._ensure_bm25()
        assert self._bm25 is not None
        ranked = self._bm25.search(query, limit=limit)
        return [
            {"id": self._bm25_ids[idx], "score": score}
            for idx, score in ranked
        ]

    def _docs_by_ids(self, ids: List[str]) -> Dict[str, Dict[str, object]]:
        all_docs = self.store.get_all()
        return {str(d["id"]): d for d in all_docs}

    def retrieve(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, object]] = None,
        k: Optional[int] = None,
    ) -> List[RetrievedDoc]:
        """Hybrid vector + BM25 retrieval (RRF fused) without generation.

        More candidates are pulled from each source than the final ``k`` so
        that exact-identifier chunks ranked just outside the top of either
        list still survive fusion.
        """
        limit = k or self.config.top_k
        candidate_k = limit * 2
        query_vec = self.store.embedder.embed_query(query)
        vector_hits = self.store.search(query_vec, limit=candidate_k, metadata_filter=metadata_filter)
        bm25_hits = self._bm25_results(query, limit=candidate_k)

        vector_ids = [str(h["id"]) for h in vector_hits]
        bm25_ids = [h["id"] for h in bm25_hits]
        docs_by_id = self._docs_by_ids(vector_ids + bm25_ids)

        # The BM25 leg runs over the full corpus, so the same pre-search
        # metadata filter must be applied to its results before fusion.
        if metadata_filter:
            bm25_hits = [
                h
                for h in bm25_hits
                if matches_metadata(docs_by_id[h["id"]]["metadata"], metadata_filter)
            ]
            bm25_ids = [h["id"] for h in bm25_hits]

        fused = reciprocal_rank_fusion(
            [vector_ids, bm25_ids], k=self.config.rrf_k, top_n=limit
        )

        contexts: List[RetrievedDoc] = []
        for i, entry in enumerate(fused):
            doc = docs_by_id.get(entry["id"])
            if doc is None:
                continue
            contexts.append(
                RetrievedDoc(
                    text=doc["text"],
                    metadata=doc["metadata"],
                    score=entry["score"],
                    rank=i,
                )
            )
        return contexts

    def answer(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, object]] = None,
    ) -> RAGResult:
        start = time.perf_counter()
        contexts = self.retrieve(query, metadata_filter=metadata_filter)
        result = self.generator.generate(query, [c.text for c in contexts])
        latency = time.perf_counter() - start + result.latency
        return RAGResult(
            query=query,
            answer=result.answer,
            contexts=contexts,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency=latency,
            retrieval_rounds=1,
            trace=[f"hybrid: vector + bm25 -> RRF top-{len(contexts)}"],
        )
