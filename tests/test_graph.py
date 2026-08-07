"""Tests for the graph-based RAG architecture."""

from __future__ import annotations

from rag.graph_rag import KnowledgeGraph
from tests import RAGTestCase


class TestKnowledgeGraph(RAGTestCase):
    def test_identifier_edge_links_chunks(self) -> None:
        docs = [
            {
                "id": "a",
                "text": "Credits are blocked with error ERR-6602.",
                "metadata": {"doc_id": "credit", "chunk_index": 0},
            },
            {
                "id": "b",
                "text": "## ERR-6602 means the balance is overdue.",
                "metadata": {"doc_id": "codes", "chunk_index": 0},
            },
            {
                "id": "c",
                "text": "Radios are broadcasting.",
                "metadata": {"doc_id": "spec", "chunk_index": 0},
            },
        ]
        graph = KnowledgeGraph(docs)
        self.assertIn("b", graph.neighbors("a"))
        self.assertIn("a", graph.neighbors("b"))
        self.assertNotIn("c", graph.neighbors("a"))

    def test_document_edge_links_consecutive_chunks(self) -> None:
        docs = [
            {
                "id": "s0",
                "text": "First part of the procedure.",
                "metadata": {"doc_id": "guide", "chunk_index": 0},
            },
            {
                "id": "s1",
                "text": "Second part of the procedure.",
                "metadata": {"doc_id": "guide", "chunk_index": 1},
            },
        ]
        graph = KnowledgeGraph(docs)
        self.assertIn("s1", graph.neighbors("s0"))
        self.assertIn("s0", graph.neighbors("s1"))

    def test_pagerank_concentrates_on_seed(self) -> None:
        docs = [
            {"id": "a", "text": "troubleshooting guide body", "metadata": {"doc_id": "g", "chunk_index": 0}},
            {"id": "b", "text": "another troubleshooting guide body", "metadata": {"doc_id": "g", "chunk_index": 1}},
        ]
        graph = KnowledgeGraph(docs)
        scores = graph.personalized_pagerank({"a": 1.0})
        self.assertGreater(scores["a"], scores["b"])


class TestGraphRAG(RAGTestCase):
    def test_plain_query_answers(self) -> None:
        result = self.pipeline.graph.answer("How much does a technician dispatch cost?")
        self.assertTrue(result.answer)
        self.assertIn("150", result.answer)
        self.assertTrue(any("graph" in t for t in result.trace))

    def test_identifier_hop_pulls_in_code_definition(self) -> None:
        query = (
            "A support agent wants to apply a $150.00 credit for a 6-hour outage "
            "without supervisor approval. Which policy threshold blocks the credit, "
            "and which error code applies if the account is also in arrears?"
        )
        contexts = self.pipeline.graph.retrieve(query, k=6)
        texts = [c.text for c in contexts]
        sources = {c.source for c in contexts}
        self.assertIn("service_credit_policy.md", sources)
        self.assertTrue(
            any("ERR-6602" in t for t in texts),
            f"expected the ERR-6602 definition to be pulled in by the graph:\n{texts}",
        )

    def test_metadata_filter_respected(self) -> None:
        contexts = self.pipeline.graph.retrieve(
            "What does ERR-9910 mean?",
            metadata_filter={"category": "troubleshooting", "source_doc": "error_code_reference.md"},
            k=4,
        )
        self.assertTrue(contexts)
        for c in contexts:
            self.assertEqual(c.source, "error_code_reference.md")

    def test_retrieval_dedups_seed_and_expansion(self) -> None:
        contexts = self.pipeline.graph.retrieve(
            "What is the fix for ERR-2210?", k=10
        )
        ids = [c.metadata.get("point_id") for c in contexts]
        self.assertEqual(len(ids), len(set(ids)))
