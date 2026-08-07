"""Shared types for the retrieval architectures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RetrievedDoc:
    """A document surfaced by a retrieval step."""

    text: str
    metadata: Dict[str, object] = field(default_factory=dict)
    score: float = 0.0
    rank: int = 0

    @property
    def source(self) -> str:
        return str(self.metadata.get("source_doc", "unknown"))


@dataclass
class RAGResult:
    """Output of a full RAG query."""

    query: str
    answer: str
    contexts: List[RetrievedDoc] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency: float = 0.0
    retrieval_rounds: int = 1
    trace: List[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def grounded(self) -> bool:
        """True when the answer is drawn from at least one retrieved chunk."""
        return bool(self.contexts)


class RAGArchitecture(ABC):
    """Common interface implemented by every retrieval pipeline."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def answer(self, query: str, metadata_filter: Optional[Dict[str, object]] = None) -> RAGResult:
        ...

    def describe(self) -> str:
        return self.name
