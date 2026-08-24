"""Vector database layer backed by Qdrant.

A real vector store is used (Qdrant, in-process local mode via
``qdrant-client``) with:

* an **HNSW ANN index** configured at collection creation,
* a **metadata payload store** attached to every vector,
* **payload indexes** (keyword on ``category`` / ``model``, datetime on
  ``doc_date``) so queries can filter *before* similarity search, not just
  after.

Nothing here is a bare list of floats: ids, vectors, and payload metadata are
managed by the store, and all searches go through the ANN index.
"""

from __future__ import annotations

import hashlib
import warnings
from typing import Dict, Iterable, List, Optional

import numpy as np

from rag.config import RAGConfig
from rag.embeddings import EmbeddingProvider
from rag.ingest import Chunk

try:
    from qdrant_client import QdrantClient, models
    from qdrant_client.http.exceptions import UnexpectedResponse
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "qdrant-client is required. Install it with `pip install qdrant-client`."
    ) from exc

_RANGE_OPS = {"__gte", "__lte", "__gt", "__lt"}
_MATCH_OPS = {"__in"}


def chunk_to_point_id(doc_id: str, chunk_index: int) -> int:
    """Stable integer point id so re-ingesting is idempotent."""
    digest = hashlib.sha256(f"{doc_id}#{chunk_index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little")


# One QdrantClient per resolved storage path. Qdrant local mode takes an
# exclusive file lock per folder, so a second instance (e.g. the chat
# agent's RAG pipeline plus the /api/rag routes) must reuse the first
# client instead of opening its own.
_shared_clients: Dict[str, QdrantClient] = {}


def _shared_client(path: str) -> QdrantClient:
    from pathlib import Path

    key = str(Path(path).resolve())
    if key not in _shared_clients:
        _shared_clients[key] = QdrantClient(
            path=path,
            # Sync endpoints run in FastAPI's threadpool, so the shared
            # client must be usable from any thread.
            force_disable_check_same_thread=True,
        )
    return _shared_clients[key]


class VectorStore:
    """Thin, typed wrapper over a Qdrant collection."""

    def __init__(self, config: RAGConfig, embedder: EmbeddingProvider) -> None:
        self.config = config
        self.embedder = embedder
        self.client = _shared_client(config.vector_db_path)
        self.collection = config.collection_name

    # --- collection lifecycle ---

    def ensure_collection(self) -> None:
        """Create the collection with an HNSW index and payload indexes."""
        exists = False
        try:
            exists = self.client.collection_exists(self.collection)
        except (UnexpectedResponse, AttributeError):
            try:
                self.client.get_collection(self.collection)
                exists = True
            except Exception:
                exists = False

        if not exists:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=self.embedder.dim,
                    distance=models.Distance[self.config.distance.upper()],
                    hnsw_config=models.HnswConfigDiff(
                        m=self.config.hnsw_m,
                        ef_construct=self.config.hnsw_ef_construct,
                    ),
                ),
                # Enable on-disk HNSW + payload for local mode.
                on_disk_payload=True,
            )

        # Metadata indexes enable pre-search filtering on these payload fields.
        self._ensure_payload_index("category", models.PayloadSchemaType.KEYWORD)
        self._ensure_payload_index("model", models.PayloadSchemaType.KEYWORD)
        self._ensure_payload_index("doc_date", models.PayloadSchemaType.DATETIME)
        self._ensure_payload_index("source_doc", models.PayloadSchemaType.KEYWORD)

    def _ensure_payload_index(self, field: str, schema) -> None:
        try:
            self.client.get_payload_index(self.collection, field_name=field)
        except Exception:
            try:
                with warnings.catch_warnings():
                    # In local (embedded) mode qdrant reports that payload
                    # indexes are only advisory; they still define the
                    # metadata index and take effect in server mode.
                    warnings.simplefilter("ignore")
                    self.client.create_payload_index(
                        collection_name=self.collection,
                        field_name=field,
                        field_schema=schema,
                    )
            except Exception:
                # Index may already exist in a concurrent/reloaded store.
                pass

    def delete_collection(self) -> None:
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    def recreate(self) -> None:
        self.delete_collection()
        self.ensure_collection()

    # --- writes ---

    def upsert_chunks(self, chunks: List[Chunk]) -> int:
        """Embed and store chunks. Returns the number of points written."""
        if not chunks:
            return 0
        vectors = self.embedder.embed([c.text for c in chunks])
        points = [
            models.PointStruct(
                id=chunk_to_point_id(
                    str(c.metadata.get("doc_id", "")),
                    int(c.metadata.get("chunk_index", 0)),
                ),
                vector=vectors[i].tolist(),
                payload={"text": c.text, "point_id": chunk_to_point_id(
                    str(c.metadata.get("doc_id", "")),
                    int(c.metadata.get("chunk_index", 0)),
                ), **c.metadata},
            )
            for i, c in enumerate(chunks)
        ]
        self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    def index_documents(self, chunks: List[Chunk]) -> int:
        """Idempotent full rebuild of the collection from chunks."""
        self.recreate()
        return self.upsert_chunks(chunks)

    # --- reads ---

    def count(self) -> int:
        try:
            return self.client.count(self.collection).count
        except Exception:
            return 0

    def get_all(self, limit: int = 100_000) -> List[Dict[str, object]]:
        """Scroll every stored point (used to build the BM25 index)."""
        result = self.client.scroll(
            collection_name=self.collection,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        docs = []
        for point in result[0]:
            payload = dict(point.payload or {})
            docs.append(
                {
                    "id": point.id,
                    "text": payload.pop("text", ""),
                    "metadata": payload,
                }
            )
        return docs

    # --- search ---

    def search(
        self,
        query_vector: np.ndarray,
        limit: int = 4,
        metadata_filter: Optional[Dict[str, object]] = None,
    ) -> List[Dict[str, object]]:
        """ANN similarity search with optional pre-search metadata filtering.

        ``metadata_filter`` is translated into a Qdrant ``query_filter`` that
        is applied by the index before the HNSW walk. Supported forms:

        * ``{"category": "policy"}`` -- exact keyword match
        * ``{"model": ["Nextlink-Optic-V1", "Nextlink-Coax-V2"]}`` -- ``__in``
        * ``{"doc_date__lte": "2026-06-01"}`` -- range match on the payload
        """
        query_filter = build_query_filter(metadata_filter) if metadata_filter else None
        result = self.client.query_points(
            collection_name=self.collection,
            query=query_vector.tolist(),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        hits = []
        for point in result.points:
            payload = dict(point.payload or {})
            hits.append(
                {
                    "id": point.id,
                    "score": float(point.score),
                    "text": payload.pop("text", ""),
                    "metadata": payload,
                }
            )
        return hits

    # --- document management ---

    def list_documents(self) -> List[Dict[str, object]]:
        """List all unique documents with their metadata and chunk counts."""
        all_points = self.get_all(limit=100_000)
        docs: Dict[str, Dict[str, object]] = {}
        for item in all_points:
            meta = item["metadata"]
            doc_id = str(meta.get("doc_id", ""))
            if not doc_id:
                continue
            if doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id,
                    "source_doc": meta.get("source_doc", ""),
                    "category": meta.get("category", ""),
                    "model": meta.get("model", ""),
                    "doc_date": meta.get("doc_date", ""),
                    "chunk_count": 0,
                }
            docs[doc_id]["chunk_count"] += 1
        return list(docs.values())

    def get_document(self, doc_id: str) -> Optional[Dict[str, object]]:
        """Get a single document's metadata and chunks by doc_id."""
        all_points = self.get_all(limit=100_000)
        chunks = []
        meta = None
        for item in all_points:
            if item["metadata"].get("doc_id") == doc_id:
                if meta is None:
                    meta = dict(item["metadata"])
                chunks.append({"text": item["text"], "metadata": item["metadata"]})
        if meta is None:
            return None
        return {
            "doc_id": doc_id,
            "source_doc": meta.get("source_doc", ""),
            "category": meta.get("category", ""),
            "model": meta.get("model", ""),
            "doc_date": meta.get("doc_date", ""),
            "chunk_count": len(chunks),
            "chunks": chunks,
        }

    def delete_document(self, doc_id: str) -> bool:
        """Delete all chunks belonging to a document."""
        all_points = self.get_all(limit=100_000)
        point_ids = [
            item["id"]
            for item in all_points
            if item["metadata"].get("doc_id") == doc_id
        ]
        if not point_ids:
            return False
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.PointIdsList(points=point_ids),
        )
        return True

    def add_document(
        self,
        doc_id: str,
        text: str,
        category: str = "knowledge",
        model: str = "all",
        doc_date: str = "2026-01-01",
        source_doc: str = "",
    ) -> int:
        """Add a single document, chunking it and upserting into the store."""
        from rag.ingest import Chunk, split_sections, _chunk_text
        from rag.config import RAGConfig

        config = RAGConfig()
        raw = Chunk(
            text=text,
            metadata={
                "doc_id": doc_id,
                "source_doc": source_doc or f"{doc_id}.md",
                "category": category,
                "model": model,
                "doc_date": doc_date,
            },
        )
        sections = split_sections(raw.text)
        chunks: List[Chunk] = []
        chunk_index = 0
        for title, body in sections:
            for piece in _chunk_text(body, config.chunk_size, config.chunk_overlap):
                metadata = dict(raw.metadata)
                metadata["section"] = title or "Introduction"
                metadata["chunk_index"] = chunk_index
                metadata["chunk_id"] = f"{doc_id}#{chunk_index}"
                chunks.append(Chunk(text=piece, metadata=metadata))
                chunk_index += 1
        return self.upsert_chunks(chunks)

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass


def build_query_filter(
    metadata_filter: Dict[str, object],
) -> "models.Filter":
    """Translate a flat dict into a Qdrant pre-search filter.

    Field names may carry one of the suffixes ``__gte``, ``__lte``, ``__gt``,
    ``__lt`` (range) or ``__in`` (multi-value match). Bare keys are exact
    keyword matches.
    """
    conditions: List[models.FieldCondition] = []
    for raw_key, value in metadata_filter.items():
        op = None
        key = raw_key
        for suffix in _RANGE_OPS:
            if raw_key.endswith(suffix):
                op = ("range", suffix)
                key = raw_key[: -len(suffix)]
                break
        for suffix in _MATCH_OPS:
            if raw_key.endswith(suffix):
                op = ("match", suffix)
                key = raw_key[: -len(suffix)]
                break

        if op and op[0] == "range":
            condition = models.FieldCondition(
                key=key,
                range=models.Range(
                    **{op[1].lstrip("_"): value},  # gte/lte/gt/lt
                ),
            )
        elif op and op[0] == "match":
            values = list(value) if isinstance(value, (list, tuple, set)) else [value]
            condition = models.FieldCondition(
                key=key, match=models.MatchAny(any=values)
            )
        else:
            condition = models.FieldCondition(
                key=key, match=models.MatchValue(value=value)
            )
        conditions.append(condition)

    return models.Filter(must=conditions)


def matches_metadata(metadata: Dict[str, object], metadata_filter: Dict[str, object]) -> bool:
    """Python-side mirror of :func:`build_query_filter`.

    Used to apply the same pre-search metadata filter to the BM25 leg of the
    hybrid retriever, which does not run inside Qdrant.
    """
    for raw_key, value in metadata_filter.items():
        op = None
        key = raw_key
        for suffix in _RANGE_OPS:
            if raw_key.endswith(suffix):
                op = ("range", suffix.lstrip("_"))
                key = raw_key[: -len(suffix)]
                break
        for suffix in _MATCH_OPS:
            if raw_key.endswith(suffix):
                op = ("match", suffix.lstrip("_"))
                key = raw_key[: -len(suffix)]
                break

        field_value = metadata.get(key)
        if op is None:
            if not (isinstance(field_value, (list, tuple, set)) and value in field_value) and field_value != value:
                return False
        elif op[0] == "match":
            values = list(value) if isinstance(value, (list, tuple, set)) else [value]
            if isinstance(field_value, (list, tuple, set)):
                if not set(field_value) & set(values):
                    return False
            elif field_value not in values:
                return False
        else:  # range
            if field_value is None:
                return False
            try:
                field_num = float(field_value)
                num = float(value)
            except (TypeError, ValueError):
                return False
            if op[1] == "gte" and not field_num >= num:
                return False
            if op[1] == "lte" and not field_num <= num:
                return False
            if op[1] == "gt" and not field_num > num:
                return False
            if op[1] == "lt" and not field_num < num:
                return False
    return True
