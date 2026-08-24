"""End-to-end pipeline tests: indexing, answering, verification retry."""

from __future__ import annotations

from rag.types import RetrievedDoc
from tests import RAGTestCase


class TestIndexing(RAGTestCase):
    def test_corpus_indexed(self) -> None:
        self.assertGreater(self.pipeline.corpus_size, 0)

    def test_reindex_is_idempotent_in_count(self) -> None:
        before = self.pipeline.corpus_size
        written = self.pipeline.reindex()
        self.assertGreater(written, 0)
        self.assertEqual(self.pipeline.corpus_size, before)


class TestAnswer(RAGTestCase):
    def test_hybrid_default_arch(self) -> None:
        result = self.pipeline.answer("What does ERR-4091 mean?", architecture="hybrid")
        self.assertTrue(result.answer)
        self.assertTrue(result.contexts)

    def test_metadata_filter_pipeline(self) -> None:
        result = self.pipeline.answer(
            "What does ERR-9910 mean?",
            architecture="hybrid",
            metadata_filter={"category": "troubleshooting", "source_doc": "error_code_reference.md"},
        )
        # LLM output sometimes renders the code with a non-breaking hyphen.
        normalized = result.answer.upper().replace("\u2011", "-").replace("\u2013", "-")
        self.assertIn("ERR-9910", normalized)
        for c in result.contexts:
            self.assertEqual(c.source, "error_code_reference.md")

    def test_verify_gate_appends_trace(self) -> None:
        result = self.pipeline.answer("What is the cost of a technician dispatch?", verify=True)
        self.assertTrue(any("self-rag gate" in t for t in result.trace))

    def test_verify_false_skips_gate(self) -> None:
        result = self.pipeline.answer("What is the cost of a technician dispatch?", verify=False)
        self.assertFalse(any("self-rag gate" in t for t in result.trace))

    def test_unverified_retry_routes_to_agentic(self) -> None:
        # A query with no grounding should attempt the agentic retry path.
        result = self.pipeline.answer(
            "What is the procedure for a quantum-entanglement refund?",
            architecture="hybrid",
            verify=True,
        )
        self.assertTrue(any("self-rag" in t for t in result.trace))


class TestMemoryRecallGate(RAGTestCase):
    def test_verify_memory_recall_returns_verdict_dict(self) -> None:
        recalled = [
            RetrievedDoc(text="Account 2 reported Wi-Fi drops near an airport."),
            RetrievedDoc(text="ERR-7745 means DFS radar interference."),
        ]
        verdict = self.pipeline.verify_memory_recall(
            "What caused the Wi-Fi drops for account 2?", recalled
        )
        self.assertIn("passed", verdict)
        self.assertIn("retrieval", verdict)
        self.assertGreaterEqual(len(verdict["retrieval"]), 1)
