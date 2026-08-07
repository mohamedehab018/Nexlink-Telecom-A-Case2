"""Tests for corpus ingestion and chunking."""

from __future__ import annotations

import tempfile
from pathlib import Path

from rag.config import load_config
from rag.ingest import (
    chunk_documents,
    load_and_chunk,
    load_documents,
    parse_front_matter,
    split_sections,
)
from tests import TestBase

_SAMPLE = """\
---
category: hardware
model: Nextlink-Optic-V1
source_doc: sample_spec.md
---

# Nextlink-Optic-V1 — Sample Spec

## 3. LED Reference

The Wi-Fi LED is solid blue while the radios are broadcasting.

## ERR-4091 — CREDIT_LIMIT_EXCEEDED

A billing limit was exceeded.
"""


class TestFrontMatter(TestBase):
    def test_parses_front_matter_keys(self) -> None:
        meta = parse_front_matter(_SAMPLE)
        self.assertEqual(meta["category"], "hardware")
        self.assertEqual(meta["model"], "Nextlink-Optic-V1")

    def test_missing_front_matter_is_empty(self) -> None:
        self.assertEqual(parse_front_matter("# Just a title\n"), {})

    def test_front_matter_stripped_from_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample_spec.md"
            path.write_text(_SAMPLE, encoding="utf-8")
            docs = load_documents(tmp)
            self.assertNotIn("category:", docs[0].text)
            self.assertEqual(docs[0].metadata["source_doc"], "sample_spec.md")


class TestSectionSplitting(TestBase):
    def test_headings_produce_sections(self) -> None:
        sections = split_sections(_SAMPLE)
        titles = [title for title, _ in sections]
        self.assertIn("3. LED Reference", titles)
        self.assertIn("ERR-4091 — CREDIT_LIMIT_EXCEEDED", titles)

    def test_heading_kept_in_body(self) -> None:
        sections = dict(split_sections(_SAMPLE))
        self.assertIn("## ERR-4091", sections["ERR-4091 — CREDIT_LIMIT_EXCEEDED"])


class TestChunking(TestBase):
    def test_chunk_inherits_metadata_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample_spec.md"
            path.write_text(_SAMPLE, encoding="utf-8")
            cfg = load_config(corpus_dirs=[tmp])
            chunks = chunk_documents(load_documents(tmp), cfg)
            for chunk in chunks:
                self.assertEqual(chunk.metadata["source_doc"], "sample_spec.md")
                self.assertIn("chunk_index", chunk.metadata)
                self.assertEqual(chunk.metadata["chunk_id"], f"{chunk.doc_id}#{chunk.metadata['chunk_index']}")

    def test_identifier_present_in_its_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "sample_spec.md").write_text(_SAMPLE, encoding="utf-8")
            cfg = load_config(corpus_dirs=[tmp])
            chunks = chunk_documents(load_documents(tmp), cfg)
            self.assertTrue(
                any("ERR-4091" in c.text for c in chunks),
                "error code only in a heading must still be retrievable",
            )

    def test_real_corpus_chunks_are_nonempty(self) -> None:
        from tests import _CORPUS

        cfg = load_config(corpus_dirs=[str(_CORPUS)])
        chunks = load_and_chunk([str(_CORPUS)], cfg)
        self.assertGreater(len(chunks), 0)
        self.assertTrue(all(c.text.strip() for c in chunks))
