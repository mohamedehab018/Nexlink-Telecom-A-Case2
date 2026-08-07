"""Shared fixtures for RAG tests.

Tests use the deterministic offline embedder and a temporary vector store so
they never depend on an API key, a network, or the developer's local index.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag.config import load_config
from rag.pipeline import RAGPipeline

_CORPUS = Path(__file__).resolve().parents[1] / "rag" / "corpus"


class RAGTestCase(unittest.TestCase):
    """Base case with a fresh, disposable pipeline per test."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        config = load_config(
            embedding_provider="offline",
            use_llm_critic=False,
            relevance_threshold=0.20,
            relevance_score_threshold=0.20,
            vector_db_path=str(Path(self._tmpdir.name) / "vector_db"),
            corpus_dirs=[str(_CORPUS)],
        )
        self.config = config
        self.pipeline = RAGPipeline(config=config, auto_index=True)

    def tearDown(self) -> None:
        try:
            self.pipeline.store.close()
        finally:
            self._tmpdir.cleanup()


class TestBase(unittest.TestCase):
    """Bare-bones base for tests that do not need a full pipeline."""
