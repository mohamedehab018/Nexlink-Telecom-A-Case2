"""Production RAG pipeline assembly.

``RAGPipeline`` wires together the vector store, corpus index, the three
retrieval architectures, the generator, and the Self-RAG verification gate,
exposing a single ``answer()`` entry point used by the agent loop.
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional

from rag.agentic import AgenticRAG
from rag.config import RAGConfig, load_config
from rag.embeddings import EmbeddingProvider, create_embedding_provider
from rag.generators import ExtractiveGenerator, Generator, GroqGenerator
from rag.ingest import Chunk, load_and_chunk
from rag.retrievers import HybridSearch, NaiveRAG
from rag.self_rag import SelfRAGVerifier
from rag.types import RAGArchitecture, RAGResult, RetrievedDoc
from rag.vector_store import VectorStore


class RAGPipeline:
    """High-level facade over the retrieval + verification stack."""

    def __init__(
        self,
        config: Optional[RAGConfig] = None,
        embedder: Optional[EmbeddingProvider] = None,
        generator: Optional[Generator] = None,
        auto_index: bool = True,
    ) -> None:
        self.config = config or load_config()
        self.embedder = embedder or create_embedding_provider(self.config)
        self.generator = generator or self._default_generator()
        self.store = VectorStore(self.config, self.embedder)
        self.verifier = SelfRAGVerifier(
            self.config, embedder=self.embedder, use_llm=bool(self.config.use_llm_critic and self.config.groq_api_key)
        )

        self.naive = NaiveRAG(self.store, self.generator, self.config)
        self.hybrid = HybridSearch(self.store, self.generator, self.config)
        self.agentic = AgenticRAG(
            self.store, self.generator, self.config, hybrid=self.hybrid
        )
        self.architectures: Dict[str, RAGArchitecture] = {
            "naive": self.naive,
            "hybrid": self.hybrid,
            "agentic": self.agentic,
        }

        if auto_index:
            self._prepare_index()

    def _prepare_index(self) -> None:
        """Fit the embedder, create/refresh the collection, and index if empty."""
        chunks = load_and_chunk(self.config.corpus_dirs, self.config)
        try:
            self.embedder.fit([c.text for c in chunks])
        except TypeError:
            pass
        self.store.ensure_collection()
        if self._collection_dim_mismatch():
            self.store.recreate()
        if self.store.count() == 0:
            self.store.upsert_chunks(chunks)

    def _collection_dim_mismatch(self) -> bool:
        try:
            info = self.store.client.get_collection(self.store.collection)
            size = info.config.params.vectors.size
            return int(size) != self.embedder.dim
        except Exception:
            return False

    def _default_generator(self) -> Generator:
        if self.config.groq_api_key:
            return GroqGenerator(model=self.config.llm_model, api_key=self.config.groq_api_key)
        return ExtractiveGenerator()

    # --- indexing ---

    def reindex(self, chunks: Optional[List[Chunk]] = None) -> int:
        if chunks is None:
            chunks = load_and_chunk(self.config.corpus_dirs, self.config)
        try:
            self.embedder.fit([c.text for c in chunks])
        except TypeError:
            pass
        if self._collection_dim_mismatch():
            self.store.recreate()
        else:
            self.store.ensure_collection()
        written = self.store.upsert_chunks(chunks)
        self.hybrid._bm25 = None  # force BM25 rebuild on next use
        return written

    @property
    def corpus_size(self) -> int:
        return self.store.count()

    # --- querying ---

    def answer(
        self,
        query: str,
        architecture: str = "hybrid",
        metadata_filter: Optional[Dict[str, object]] = None,
        verify: bool = True,
    ) -> RAGResult:
        """Answer ``query`` with the chosen architecture, optionally gated by
        Self-RAG verification.

        When verification fails, the pipeline retries the query with the
        agentic architecture; if that still cannot produce a grounded answer
        it returns the unverified result flagged via ``trace`` so the caller
        can respond honestly (e.g., "I couldn't find that in our knowledge
        base") instead of hallucinating.
        """
        arch = self.architectures.get(architecture, self.hybrid)
        result = arch.answer(query, metadata_filter=metadata_filter)
        if not verify or not result.contexts:
            return result

        verdict = self.verifier.verify_rag(query, result)
        result.trace.append(
            f"self-rag gate: {'PASS' if verdict.passed else 'FAIL'} "
            f"(generation={verdict.generation.level}, "
            f"relevant={sum(v.relevant for v in verdict.retrieval)}/{len(verdict.retrieval)})"
        )
        if verdict.passed:
            return result

        if architecture != "agentic":
            retry = self.agentic.answer(query, metadata_filter=metadata_filter)
            retry_verdict = self.verifier.verify_rag(query, retry)
            retry.trace.append(
                f"self-rag retry (agentic): {'PASS' if retry_verdict.passed else 'FAIL'} "
                f"(generation={retry_verdict.generation.level})"
            )
            if retry_verdict.passed:
                return retry
            result.trace.append("agentic retry failed grounding; returning unverified")
            return result

        result.trace.append("verification failed; answer not grounded")
        return result

    def verify_memory_recall(
        self, query: str, recalled: List[RetrievedDoc]
    ) -> Dict[str, object]:
        """Apply the Self-RAG gate to episodic/semantic memory recalls.

        The memory subsystem can call this before surfacing a recalled memory
        to the user. Returns a verdict dict with ``passed`` and per-doc
        relevance.
        """
        verdict = self.verifier.verify_memory_recall(query, recalled)
        return {
            "passed": verdict.passed,
            "retrieval": [
                {"text": c.text, "metadata": c.metadata, "relevant": v.relevant, "score": v.score}
                for c, v in zip(verdict.contexts, verdict.retrieval)
            ],
            "notes": verdict.notes,
            "latency": verdict.latency,
        }


def index_database(config: Optional[RAGConfig] = None) -> int:
    """Build/refresh the vector index from the corpus (CLI helper)."""
    cfg = config or load_config()
    pipeline = RAGPipeline(config=cfg, auto_index=False)
    written = pipeline.reindex()
    pipeline.store.close()
    return written


if __name__ == "__main__":
    import sys

    cfg = load_config()
    if os.getenv("RAG_EMBEDDING_PROVIDER", "sentence_transformers").strip() in {"ngram", "hash"}:
        print(f"[index] embedding provider: {cfg.embedding_provider}")
    start = time.perf_counter()
    n = index_database(cfg)
    print(f"[index] wrote {n} chunks in {time.perf_counter() - start:.2f}s")
    print(f"[index] vector db at: {cfg.vector_db_path}")
