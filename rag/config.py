"""Environment-driven configuration for the RAG subsystem.

All secrets / API keys are read from the environment (loaded from a .env file
by the caller) and never hardcoded here. Everything else has a sensible
default so the system runs without any configuration.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional


def _corpus_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")


def _default_vector_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "vector_db")


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RAGConfig:
    """Central configuration for the retrieval pipelines."""

    # --- vector store ---
    vector_db_path: str = field(
        default_factory=lambda: os.getenv("RAG_VECTOR_PATH", _default_vector_path())
    )
    collection_name: str = field(
        default_factory=lambda: os.getenv("RAG_COLLECTION", "nextlink_knowledge")
    )
    hnsw_m: int = field(default_factory=lambda: int(os.getenv("RAG_HNSW_M", "16")))
    hnsw_ef_construct: int = field(
        default_factory=lambda: int(os.getenv("RAG_HNSW_EF_CONSTRUCT", "100"))
    )
    distance: str = field(default_factory=lambda: os.getenv("RAG_DISTANCE", "Cosine"))

    # --- embeddings ---
    embedding_provider: str = field(
        default_factory=lambda: os.getenv("RAG_EMBEDDING_PROVIDER", "sentence_transformers")
    )
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )
    openai_embedding_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    )
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("RAG_EMBEDDING_DIM", "384")))

    # --- chunking ---
    chunk_size: int = field(default_factory=lambda: int(os.getenv("RAG_CHUNK_SIZE", "512")))
    chunk_overlap: int = field(default_factory=lambda: int(os.getenv("RAG_CHUNK_OVERLAP", "64")))

    # --- retrieval ---
    top_k: int = field(default_factory=lambda: int(os.getenv("RAG_TOP_K", "4")))
    rrf_k: int = field(default_factory=lambda: int(os.getenv("RAG_RRF_K", "60")))

    # --- agentic RAG ---
    max_retrieval_rounds: int = field(
        default_factory=lambda: int(os.getenv("RAG_MAX_ROUNDS", "3"))
    )
    relevance_threshold: float = field(
        default_factory=lambda: float(os.getenv("RAG_RELEVANCE_THRESHOLD", "0.20"))
    )

    # --- self-rag verification ---
    use_llm_critic: bool = field(
        default_factory=lambda: env_bool("RAG_USE_LLM_CRITIC", default=False)
    )
    relevance_score_threshold: float = field(
        default_factory=lambda: float(os.getenv("RAG_VERIFY_RELEVANCE_THRESHOLD", "0.20"))
    )

    # --- corpus ---
    corpus_dirs: List[str] = field(
        default_factory=lambda: [os.getenv("RAG_CORPUS_DIR", _corpus_dir())]
    )

    # --- LLM (shared with the agent) ---
    llm_model: str = field(
        default_factory=lambda: os.getenv(
            "LLM_MODEL",
            # Default must match the active provider: Groq's llama-3.3 id was
            # retired there; on OpenRouter the equivalent lives at meta-llama/*.
            "meta-llama/llama-3.3-70b-instruct"
            if os.getenv("OPENROUTER_API_KEY")
            else "llama-3.3-70b-versatile",
        )
    )

    @property
    def groq_api_key(self) -> Optional[str]:
        """API key for whichever provider is configured (OpenRouter preferred)."""
        return os.getenv("OPENROUTER_API_KEY") or os.getenv("GROQ_API_KEY")

    @property
    def using_openrouter(self) -> bool:
        return bool(os.getenv("OPENROUTER_API_KEY"))

    @property
    def api_base_url(self) -> Optional[str]:
        """Base URL override; None keeps each SDK's provider default."""
        return os.getenv("OPENROUTER_BASE_URL") or (
            "https://openrouter.ai/api/v1" if self.using_openrouter else None
        )

    @property
    def openai_api_key(self) -> Optional[str]:
        return os.getenv("OPENAI_API_KEY")


def load_config(**overrides) -> RAGConfig:
    """Build a RAGConfig, overriding any field with keyword arguments."""
    cfg = RAGConfig()
    for key, value in overrides.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg
