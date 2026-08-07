"""Tests for the agentic (LangGraph) pipeline."""

from __future__ import annotations

from rag.agentic import heuristic_decompose, heuristic_rewrite
from tests import RAGTestCase


class TestDecompose(RAGTestCase):
    def test_degenerate_anaphora_not_split(self) -> None:
        parts = heuristic_decompose(
            "Which Nextlink internet plan costs the most per month, and its price?"
        )
        self.assertEqual(len(parts), 1)

    def test_identifier_sub_queries_split(self) -> None:
        parts = heuristic_decompose(
            "The modem logs ERR-3321 after a storm. Which policy governs a dispatch?"
        )
        self.assertEqual(len(parts), 2)
        self.assertTrue(any("ERR-3321" in p for p in parts))

    def test_multiple_codes_expand(self) -> None:
        parts = heuristic_decompose("Fix ERR-4091 and ERR-6602.")
        self.assertEqual(len(parts), 2)
        self.assertTrue(all(p.startswith("What does ERR-") for p in parts))


class TestRewrite(RAGTestCase):
    def test_rewrite_keeps_identifiers(self) -> None:
        rewritten = heuristic_rewrite(
            "What is the remedy for ERR-5513?", ["What is the remedy for ERR-5513?"]
        )
        self.assertIn("ERR-5513", rewritten)


class TestAgenticAnswer(RAGTestCase):
    def test_latent_multihop_resolved_by_sub_query(self) -> None:
        query = (
            "A support agent wants to apply a $150.00 credit for a 6-hour outage "
            "without supervisor approval. Which policy threshold blocks the credit, "
            "and which error code applies if the account is also in arrears?"
        )
        result = self.pipeline.agentic.answer(query)
        self.assertTrue(result.answer)
        lowered = result.answer.lower()
        self.assertIn("err-6602", lowered)
        self.assertIn("supervisor", lowered)

    def test_plain_query_answers(self) -> None:
        result = self.pipeline.agentic.answer("What is the cost of a technician dispatch?")
        self.assertTrue(result.answer)
        self.assertIn("150", result.answer)

    def test_trace_reports_rounds(self) -> None:
        result = self.pipeline.agentic.answer("What does ERR-2210 mean?")
        self.assertGreaterEqual(result.retrieval_rounds, 1)
        self.assertTrue(any("retrieve round" in t for t in result.trace))

    def test_grades_against_retrieval_sub_query(self) -> None:
        result = self.pipeline.agentic.answer(
            "An Optic-V1 at -28 dBm logs ERR-5513. Does a 6-hour outage qualify "
            "for a service credit and how is it computed?"
        )
        lowered = result.answer.lower()
        self.assertIn("pro-rated", lowered)
        self.assertTrue(any("err-5513" in c.text.lower() for c in result.contexts))
