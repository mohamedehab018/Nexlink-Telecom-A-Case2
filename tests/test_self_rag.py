"""Tests for the Self-RAG verification gate."""

from __future__ import annotations

from rag.self_rag import HeuristicRelevance, SelfRAGVerifier
from rag.types import RetrievedDoc
from tests import RAGTestCase


def _doc(text: str, source: str = "doc.md", model: str = "all") -> RetrievedDoc:
    return RetrievedDoc(text=text, metadata={"source_doc": source, "model": model})


class TestHeuristicRelevance(RAGTestCase):
    def test_identifier_chunk_outranks_noise(self) -> None:
        score = HeuristicRelevance(embedder=self.pipeline.embedder).score(
            "What does ERR-4091 mean?",
            "ERR-4091 means the billing credit limit was exceeded.",
        )
        noise = HeuristicRelevance(embedder=self.pipeline.embedder).score(
            "What does ERR-4091 mean?",
            "Nextlink technicians follow a standard dispatch procedure.",
        )
        self.assertGreater(score, noise)

    def test_metadata_model_boosts_table_chunk(self) -> None:
        gra = HeuristicRelevance(embedder=self.pipeline.embedder)
        query = "What does a solid blue Wi-Fi LED indicate on the Nextlink-Optic-V1?"
        table = "## 3. LED Reference\n| Wi-Fi | Solid blue | Radios on and broadcasting |"
        with_meta = gra.score(query, table, {"model": "Nextlink-Optic-V1"})
        without_meta = gra.score(query, table)
        self.assertGreater(with_meta, without_meta)


class TestSelfRAGVerifier(RAGTestCase):
    def test_grounded_answer_passes(self) -> None:
        docs = [_doc("ERR-2210 fix: lock the account after three attempts within 30 days.")]
        answer = "ERR-2210 fix: lock the account after three attempts within 30 days."
        verdict = self.pipeline.verifier.verify("What is the fix for ERR-2210?", answer, docs)
        self.assertTrue(verdict.passed)
        self.assertEqual(verdict.generation.level, "supported")

    def test_no_relevant_chunks_fails(self) -> None:
        docs = [_doc("The modem resets when the power adapter is replugged.")]
        answer = "ERR-2210 means the account was locked after failed attempts."
        verdict = self.pipeline.verifier.verify("What is the fix for ERR-2210?", answer, docs)
        self.assertFalse(verdict.passed)
        self.assertIn("post-retrieval", " ".join(verdict.notes).lower())

    def test_memory_recall_gate(self) -> None:
        recalled = [
            _doc("Walter from account 2 previously reported a Wi-Fi drop near the airport."),
            _doc("ERR-7745 indicates DFS radar interference on the 5 GHz band."),
        ]
        verdict = self.pipeline.verifier.verify_memory_recall(
            "What caused the Wi-Fi drops for account 2?", recalled
        )
        # At least one recalled memory must be relevant for the gate to pass.
        self.assertTrue(any(v.relevant for v in verdict.retrieval))

    def test_verify_rag_wraps_result(self) -> None:
        result = self.pipeline.hybrid.answer("What does ERR-7745 mean?")
        verdict = self.pipeline.verifier.verify_rag(result.query, result)
        self.assertIsNotNone(verdict.generation)
