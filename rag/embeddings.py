"""Embedding providers for the RAG pipeline.

Three providers are available, selected by ``RAG_EMBEDDING_PROVIDER``:

* ``sentence_transformers`` -- real semantic embeddings from a local
  ``sentence-transformers`` model (default, preferred). Requires the optional
  dependency and a one-time model download.
* ``ngram`` / ``offline`` -- deterministic, zero-dependency embedder. Uses
  TF-IDF vectors after ``fit()`` (built from the corpus at index time) and a
  hashing fallback before fitting. Runs anywhere without a network.
* ``openai`` -- OpenAI-compatible embeddings via ``OPENAI_API_KEY``.

No secrets are hardcoded; API keys are always read from the environment.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Sequence

import numpy as np

from rag.config import RAGConfig
from rag.text_utils import tokenize

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class EmbeddingProvider(ABC):
    """A text -> fixed-dimension vector embedding provider."""

    @property
    @abstractmethod
    def dim(self) -> int:
        ...

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Return a (len(texts), dim) float32 array of normalized vectors."""
        ...

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def fit(self, texts: Sequence[str]) -> None:
        """Optional corpus-level fitting step (no-op by default)."""


class HashEmbedder(EmbeddingProvider):
    """Ultra-lightweight hashing embedder (pre-fit fallback).

    Combines token-level and character n-gram features hashed into a fixed
    vector space. Deterministic across runs and machines.
    """

    def __init__(self, dim: int = 384, ngram_min: int = 3, ngram_max: int = 4) -> None:
        self._dim = dim
        self._ngram_min = ngram_min
        self._ngram_max = ngram_max

    @property
    def dim(self) -> int:
        return self._dim

    @staticmethod
    def _hash_idx(feature: str, dim: int) -> int:
        digest = hashlib.md5(feature.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "little") % dim

    def _features(self, text: str) -> List[str]:
        lowered = text.lower()
        tokens = _TOKEN_RE.findall(lowered)
        features: List[str] = []
        for tok in tokens:
            features.append(f"t:{tok}")
            for n in range(self._ngram_min, self._ngram_max + 1):
                if len(tok) >= n:
                    for i in range(len(tok) - n + 1):
                        features.append(f"{n}:{tok[i:i+n]}")
        return features

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self._dim), dtype=np.float32)
        for row, text in enumerate(texts):
            features = self._features(text)
            if not features:
                continue
            counts: Dict[int, float] = {}
            for feat in features:
                idx = self._hash_idx(feat, self._dim)
                counts[idx] = counts.get(idx, 0.0) + 1.0
            for idx, count in counts.items():
                vectors[row, idx] = math.log1p(count)
            norm = np.linalg.norm(vectors[row])
            if norm > 0:
                vectors[row] /= norm
        return vectors


class OfflineEmbedder(EmbeddingProvider):
    """Deterministic offline embedder.

    After ``fit(corpus)`` builds a TF-IDF vector space from the corpus, which
    gives meaningful cosine similarity for keyword-dense domains (error codes,
    model names, policy terms) with no external dependencies. Before fitting,
    falls back to :class:`HashEmbedder`.
    """

    def __init__(self, max_features: int = 20_000, min_df: int = 1) -> None:
        self._max_features = max_features
        self._min_df = min_df
        self._vocab: Optional[Dict[str, int]] = None
        self._idf: Dict[str, float] = {}
        self._hash = HashEmbedder(dim=384)

    @property
    def dim(self) -> int:
        return len(self._vocab) if self._vocab else self._hash.dim

    def fit(self, texts: Sequence[str]) -> None:
        df: Dict[str, int] = {}
        for text in texts:
            for tok in set(tokenize(text)):
                df[tok] = df.get(tok, 0) + 1
        n_docs = len(texts)
        terms = sorted(
            (t for t, c in df.items() if c >= self._min_df),
            key=lambda t: (-df[t], t),
        )[: self._max_features]
        self._vocab = {t: i for i, t in enumerate(terms)}
        self._idf = {
            t: math.log(1.0 + n_docs / df[t]) for t in terms
        }

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if self._vocab is None:
            return self._hash.embed(texts)
        vocab, idf = self._vocab, self._idf
        vectors = np.zeros((len(texts), len(vocab)), dtype=np.float32)
        for row, text in enumerate(texts):
            tf: Dict[str, int] = {}
            for tok in tokenize(text):
                if tok in vocab:
                    tf[tok] = tf.get(tok, 0) + 1
            for tok, count in tf.items():
                vectors[row, vocab[tok]] = count * idf[tok]
            norm = np.linalg.norm(vectors[row])
            if norm > 0:
                vectors[row] /= norm
        return vectors

    def embed_query(self, text: str) -> np.ndarray:
        # Drop generic filler words from queries so a citation query like
        # "what does error code ERR-4091 mean" is dominated by the identifier
        # rather than by terms that equally match unrelated intro paragraphs.
        from rag.text_utils import content_tokens

        filtered = " ".join(content_tokens(text))
        return self.embed([filtered])[0]


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Real semantic embeddings via the optional sentence-transformers lib."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised on CI images
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Install it or set RAG_EMBEDDING_PROVIDER=offline."
            ) from exc
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name

    @property
    def dim(self) -> int:
        return int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        return self._model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        ).astype(np.float32)


class OpenAIEmbedder(EmbeddingProvider):
    """OpenAI-compatible embeddings (read key from the environment)."""

    def __init__(
        self, model: str = "text-embedding-3-small", api_key: Optional[str] = None
    ) -> None:
        try:
            import openai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("openai is not installed.") from exc
        self._model = model
        self._client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

    @property
    def dim(self) -> int:
        return 1536  # text-embedding-3-small

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            resp = self._client.embeddings.create(model=self._model, input=[text])
            vectors.append(resp.data[0].embedding)
        arr = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.maximum(norms, 1e-9)


def create_embedding_provider(config: RAGConfig) -> EmbeddingProvider:
    """Instantiate the embedding provider chosen by config."""
    provider = (config.embedding_provider or "sentence_transformers").strip().lower()
    if provider in {"sentence_transformers", "st", "sentence-transformers"}:
        try:
            return SentenceTransformerEmbedder(config.embedding_model)
        except RuntimeError:
            return OfflineEmbedder()
    if provider in {"ngram", "hash", "offline", "tfidf"}:
        return OfflineEmbedder()
    if provider in {"openai", "api"}:
        return OpenAIEmbedder(
            model=config.openai_embedding_model, api_key=config.openai_api_key
        )
    raise ValueError(f"Unknown embedding provider: {config.embedding_provider}")
