"""RAG package for the Nexlink AI Support System.

Grounded retrieval over Nextlink ISP policy manuals, hardware specifications,
and troubleshooting guides. Exposes the naive / hybrid / agentic retrieval
architectures plus the Self-RAG-style verification gate used by the agent.
"""

from rag.pipeline import RAGPipeline  # noqa: F401
from rag.self_rag import SelfRAGVerifier  # noqa: F401

__all__ = ["RAGPipeline", "SelfRAGVerifier"]
