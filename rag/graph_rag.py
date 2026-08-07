"""Graph-based RAG: knowledge-graph traversal over the indexed corpus.

Builds an in-memory knowledge graph over the indexed chunks and retrieves with
personalized PageRank, so contextually-linked chunks join the evidence set:

* **Document edges** -- consecutive chunks inside the same document are
  connected, so traversal can walk a full procedure or spec section.
* **Identifier edges** -- chunks that mention the same distinctive identifier
  (an ``ERR-xxxx`` error code or a ``Nextlink-...-V<n>`` hardware model) are
  linked, so a policy chunk that *cites* an error code connects to the section
  that actually *defines* that code -- exactly the cross-document hop a flat
  ranker misses.

Retrieval: hybrid search picks the seed chunks (kept verbatim), those seeds set
a personalized PageRank teleport vector whose stationary distribution selects
the reachable candidate neighborhood, and the best candidates (by cosine
similarity to the query) are appended to the context. The graph therefore
*adds* the linked evidence a flat ranker misses -- e.g. the error-code
definition behind a policy citation -- without ever displacing the
directly-relevant chunks.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Sequence

import numpy as np

from rag.config import RAGConfig
from rag.generators import Generator
from rag.retrievers import HybridSearch
from rag.types import RAGArchitecture, RAGResult, RetrievedDoc
from rag.vector_store import VectorStore, matches_metadata

# Identifier edges only join on error codes and hardware models; bare numbers
# are too noisy to be meaningful entity links.
_CODE_RE = re.compile(r"\berr-\d{4}\b", re.IGNORECASE)
_MODEL_RE = re.compile(r"\bnextlink-\w+-v\d\b", re.IGNORECASE)


class KnowledgeGraph:
    """Entity + document-structure graph over the indexed chunks.

    Node ids are the vector store's ``point_id`` values, so seed chunks
    returned by hybrid search map directly onto graph nodes.
    """

    def __init__(self, docs: Sequence[Dict[str, object]]) -> None:
        self.ids: List[str] = []
        self._index: Dict[str, int] = {}
        self._docs_by_id: Dict[str, Dict[str, object]] = {}
        self._adj: Dict[str, set] = {}
        doc_groups: Dict[str, List[str]] = {}
        for d in docs:
            nid = str(d["id"])
            self._index[nid] = len(self.ids)
            self.ids.append(nid)
            self._docs_by_id[nid] = d
            self._adj.setdefault(nid, set())
            metadata = d.get("metadata", {})
            doc_groups.setdefault(str(metadata.get("doc_id", "")), []).append(nid)
        self._add_document_edges(doc_groups)
        self._add_identifier_edges(docs)

    def _add_document_edges(self, doc_groups: Dict[str, List[str]]) -> None:
        for ids in doc_groups.values():
            ids.sort(
                key=lambda n: int(
                    self._docs_by_id[n]["metadata"].get("chunk_index", 0)
                )
            )
            for a, b in zip(ids, ids[1:]):
                self._adj.setdefault(a, set()).add(b)
                self._adj.setdefault(b, set()).add(a)

    def _add_identifier_edges(self, docs: Sequence[Dict[str, object]]) -> None:
        by_entity: Dict[str, List[str]] = {}
        for d in docs:
            text = str(d.get("text", ""))
            entities = set(_CODE_RE.findall(text)) | set(_MODEL_RE.findall(text))
            entities = {e.lower() for e in entities}
            for entity in entities:
                by_entity.setdefault(entity, []).append(str(d["id"]))
        for ids in by_entity.values():
            if len(ids) < 2:
                continue
            for i, a in enumerate(ids):
                for b in ids[i + 1 :]:
                    self._adj.setdefault(a, set()).add(b)
                    self._adj.setdefault(b, set()).add(a)

    def neighbors(self, node_id: str) -> List[str]:
        return list(self._adj.get(node_id, ()))

    def doc(self, node_id: str) -> Optional[Dict[str, object]]:
        return self._docs_by_id.get(node_id)

    def personalized_pagerank(
        self,
        teleport: Dict[str, float],
        alpha: float = 0.20,
        max_iters: int = 50,
    ) -> Dict[str, float]:
        """Personalized PageRank with ``teleport`` mass on the seed nodes."""
        n = len(self.ids)
        neighbor_idx: List[List[int]] = []
        out_deg: List[int] = []
        for nid in self.ids:
            nb = [self._index[x] for x in self._adj[nid]]
            neighbor_idx.append(nb)
            out_deg.append(len(nb))

        teleport_vec = [teleport.get(nid, 0.0) for nid in self.ids]
        p = [0.0] * n
        for _ in range(max_iters):
            p_new = [alpha * t for t in teleport_vec]
            for i in range(n):
                if p[i] == 0.0:
                    continue
                if out_deg[i] == 0:
                    p_new[i] += (1.0 - alpha) * p[i]
                    continue
                share = (1.0 - alpha) * p[i] / out_deg[i]
                for j in neighbor_idx[i]:
                    p_new[j] += share
            if all(abs(a - b) < 1e-9 for a, b in zip(p, p_new)):
                p = p_new
                break
            p = p_new
        return {self.ids[i]: score for i, score in enumerate(p)}


class GraphRAG(RAGArchitecture):
    """Graph retrieval: hybrid-seeded personalized PageRank expansion."""

    name = "Graph RAG (knowledge graph)"

    def __init__(
        self,
        store: VectorStore,
        generator: Generator,
        config: RAGConfig,
        hybrid: Optional[HybridSearch] = None,
    ) -> None:
        self.store = store
        self.generator = generator
        self.config = config
        self.hybrid = hybrid or HybridSearch(store, generator, config)
        self._graph: Optional[KnowledgeGraph] = None

    def _ensure_graph(self) -> None:
        if self._graph is None:
            self._graph = KnowledgeGraph(self.store.get_all())

    def invalidate(self) -> None:
        """Drop the cached graph so the next call rebuilds from the store."""
        self._graph = None

    def retrieve(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, object]] = None,
        k: Optional[int] = None,
        seed_k: Optional[int] = None,
        expansion_k: int = 6,
        depth: int = 2,
        alpha: float = 0.20,
    ) -> List[RetrievedDoc]:
        """Hybrid seeds + graph-expanded, semantic re-ranked context.

        The hybrid seeds are the primary evidence (kept verbatim, so graph
        retrieval can never lose what the flat ranker found). The graph's
        personalized PageRank only *selects* the candidate neighborhood --
        every chunk within ``depth`` hops of a seed. Those candidates are then
        re-ranked by cosine similarity to the query, and the best
        ``expansion_k`` *new* nodes are appended -- this is how the error-code
        definition behind a policy citation, invisible to a flat ranker, joins
        the context.
        """
        limit = k or self.config.top_k
        self._ensure_graph()
        assert self._graph is not None
        seeds = self.hybrid.retrieve(
            query, metadata_filter=metadata_filter, k=seed_k or limit
        )
        if not seeds:
            return []

        seed_ids = [str(s.metadata.get("point_id")) for s in seeds]
        teleport = {nid: max(s.score, 1e-6) for nid, s in zip(seed_ids, seeds)}
        scores = self._graph.personalized_pagerank(teleport, alpha=alpha)
        query_vec = self.store.embedder.embed_query(query)

        candidates = self._bfs(set(seed_ids), depth)
        seed_id_set = set(seed_ids)
        scored: List[tuple] = []
        for nid in candidates:
            if nid in seed_id_set:
                continue
            doc = self._graph.doc(nid)
            if doc is None:
                continue
            if metadata_filter and not matches_metadata(doc["metadata"], metadata_filter):
                continue
            doc_vec = self.store.embedder.embed_query(doc["text"])
            sim = max(float(np.dot(query_vec, doc_vec)), 0.0)
            scored.append((sim, scores.get(nid, 0.0), nid, doc))
        scored.sort(reverse=True)

        expansions: List[RetrievedDoc] = []
        for sim, ppr, nid, doc in scored[:expansion_k]:
            expansions.append(
                RetrievedDoc(
                    text=doc["text"],
                    metadata=doc["metadata"],
                    score=sim,
                    rank=len(seeds) + len(expansions),
                )
            )

        contexts: List[RetrievedDoc] = [
            RetrievedDoc(text=s.text, metadata=s.metadata, score=s.score, rank=i)
            for i, s in enumerate(seeds)
        ]
        contexts.extend(expansions)
        return contexts

    def _bfs(self, start_ids: set, depth: int) -> set:
        """All node ids reachable from ``start_ids`` within ``depth`` hops."""
        graph = self._graph
        assert graph is not None
        visited = set(start_ids)
        frontier = set(start_ids)
        for _ in range(depth):
            nxt = set()
            for nid in frontier:
                for nb in graph.neighbors(nid):
                    if nb not in visited:
                        nxt.add(nb)
                        visited.add(nb)
            frontier = nxt
        return visited

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
            trace=[
                "graph: hybrid seed -> graph neighborhood (depth 2) -> "
                f"semantic re-rank top-{len(contexts)} of {len(self._graph.ids)} nodes"
            ],
        )
