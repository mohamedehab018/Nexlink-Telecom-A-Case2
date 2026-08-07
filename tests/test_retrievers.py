"""Tests for BM25, reciprocal rank fusion, and the retrieval architectures."""

from __future__ import annotations

from rag.retrievers import BM25Index, content_tokens, reciprocal_rank_fusion
from tests import RAGTestCase


class TestBM25Index(RAGTestCase):
    def test_identifier_bonus_lifts_exact_code_section(self) -> None:
        docs = [
            "Welcome to the Nextlink support center. Error codes are handled by agents.",
            "ERR-4091 means the billing credit limit was exceeded and a hard cap applies.",
            "Credits over twenty five dollars require a supervisor approval.",
        ]
        bm25 = BM25Index(docs)
        ranked = bm25.search("What does ERR-4091 mean?", limit=3)
        self.assertEqual(ranked[0][0], 1)

    def test_content_tokens_exclude_generic_query_words(self) -> None:
        tokens = content_tokens("what does the error code ERR-2210 fix?")
        self.assertIn("err-2210", tokens)
        self.assertNotIn("the", tokens)

    def test_fallback_bm25_without_rank_bm25(self) -> None:
        import rag.retrievers as mod

        real = mod.BM25Okapi if hasattr(mod, "BM25Okapi") else None
        try:
            mod.BM25Okapi = None  # force fallback path
            bm25 = BM25Index(["one two three", "four five six"])
            self.assertEqual(len(bm25.search("two", limit=2)), 2)
        finally:
            if real is not None:
                mod.BM25Okapi = real


class TestRRF(RAGTestCase):
    def test_fusion_prefers_docs_ranked_in_both_lists(self) -> None:
        fused = reciprocal_rank_fusion(
            [["a", "b", "c"], ["b", "a", "d"]], k=60, top_n=2
        )
        self.assertEqual([e["id"] for e in fused], ["a", "b"])

    def test_top_n_limits_output(self) -> None:
        fused = reciprocal_rank_fusion([["a", "b", "c", "d"]], top_n=2)
        self.assertEqual(len(fused), 2)


class TestNaiveRAG(RAGTestCase):
    def test_answers_and_contexts(self) -> None:
        result = self.pipeline.naive.answer("What is the cost of a technician dispatch?")
        self.assertTrue(result.contexts)
        self.assertTrue(result.answer)

    def test_metadata_filter_restricts_sources(self) -> None:
        result = self.pipeline.naive.answer(
            "What does ERR-9910 mean?",
            metadata_filter={"source_doc": "error_code_reference.md"},
        )
        sources = {c.source for c in result.contexts}
        self.assertTrue(sources)
        self.assertTrue(sources <= {"error_code_reference.md"})


class TestHybridSearch(RAGTestCase):
    def test_citation_query_finds_exact_section(self) -> None:
        docs = self.pipeline.hybrid.retrieve("What does ERR-2210 mean?", k=4)
        texts = [d.text.lower() for d in docs]
        self.assertTrue(
            any("err-2210 — auth_failed" in t or "err-2210" in t for t in texts)
        )

    def test_metadata_filter_plus_bm25(self) -> None:
        docs = self.pipeline.hybrid.retrieve(
            "ERR-3321 remedy", k=4, metadata_filter={"source_doc": "coax_v2_spec.md"}
        )
        self.assertTrue(docs)
        for d in docs:
            self.assertEqual(d.source, "coax_v2_spec.md")
