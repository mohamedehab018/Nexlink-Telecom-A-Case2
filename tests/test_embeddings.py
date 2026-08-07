"""Tests for the offline embedders and text utilities."""

from __future__ import annotations

import numpy as np

from rag.embeddings import HashEmbedder, OfflineEmbedder
from rag.text_utils import content_tokens, distinctive_terms, tokenize
from tests import TestBase


class TestTokenization(TestBase):
    def test_identifier_tokens_are_atomic(self) -> None:
        self.assertIn("err-4091", tokenize("What does ERR-4091 mean?"))
        self.assertIn("nextlink-optic-v1", tokenize("Nextlink-Optic-V1"))

    def test_content_tokens_keep_identifiers(self) -> None:
        tokens = content_tokens("what does error code ERR-4091 mean")
        self.assertIn("err-4091", tokens)
        self.assertNotIn("what", tokens)

    def test_distinctive_terms(self) -> None:
        terms = distinctive_terms("ERR-4091 on a Nextlink-Coax-V2 at 6 hours")
        self.assertIn("ERR-4091", terms)
        self.assertIn("Nextlink-Coax-V2", terms)
        self.assertIn("6", terms)


class TestHashEmbedder(TestBase):
    def test_dim_and_normalization(self) -> None:
        emb = HashEmbedder(dim=128)
        vectors = emb.embed(["hello world", "hello world hello"])
        self.assertEqual(vectors.shape, (2, 128))
        self.assertAlmostEqual(np.linalg.norm(vectors[0]), 1.0, places=5)

    def test_identical_texts_match(self) -> None:
        emb = HashEmbedder(dim=128)
        a, b = emb.embed(["Nextlink Wi-Fi drop", "Nextlink Wi-Fi drop"])
        self.assertGreater(float(np.dot(a, b)), 0.99)


class TestOfflineEmbedder(TestBase):
    def test_fit_changes_dimension(self) -> None:
        emb = OfflineEmbedder()
        corpus = ["the plan costs $60 per month", "error code ERR-4091 credit limit"]
        emb.fit(corpus)
        expected = len({t for s in corpus for t in tokenize(s)})
        self.assertEqual(emb.dim, expected)

    def test_pre_fit_fallback_works(self) -> None:
        emb = OfflineEmbedder()
        v = emb.embed(["hello world"])
        self.assertEqual(v.shape, (1, emb.dim))

    def test_similar_identifiers_rank_above_generic(self) -> None:
        emb = OfflineEmbedder()
        corpus = [
            "ERR-4091 means the credit limit was exceeded",
            "The technician dispatch costs one hundred fifty dollars",
        ]
        emb.fit(corpus)
        q = emb.embed_query("What does ERR-4091 mean?")
        sims = [float(np.dot(q, emb.embed([c])[0])) for c in corpus]
        self.assertGreater(sims[0], sims[1])

    def test_query_stopword_filtering(self) -> None:
        emb = OfflineEmbedder()
        emb.fit(["solid blue LED means radios broadcasting", "the a an of it"])
        q = emb.embed_query("what does it mean?")
        self.assertEqual(np.linalg.norm(q), 0.0)  # all stopwords -> no signal
