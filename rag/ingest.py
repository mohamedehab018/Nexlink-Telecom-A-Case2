"""Document loading and chunking for the RAG corpus.

Loads Markdown documents (with optional YAML-style front-matter carrying
metadata such as category, hardware model, and document date), then chunks
them by section heading with a fixed-size overlap fallback for very long
sections. Every chunk carries a metadata payload used for pre-search
filtering in the vector store.
"""

from __future__ import annotations

import glob
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from rag.config import RAGConfig

# Front matter block: leading `---` line, then `key: value` lines, then `---`.
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_SECTION_SPLIT_RE = re.compile(r"\n{2,}")


@dataclass
class Chunk:
    """A single retrieval unit stored in the vector database."""

    text: str
    metadata: Dict[str, object] = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        return str(self.metadata.get("doc_id", ""))

    @property
    def chunk_id(self) -> str:
        return str(self.metadata.get("chunk_id", self.doc_id))


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def parse_front_matter(text: str) -> Dict[str, str]:
    """Parse a leading ``--- key: value ---`` block into a dict."""
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    metadata: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        metadata[key.strip()] = value.strip()
    return metadata


def load_documents(corpus_dir: str) -> List[Chunk]:
    """Load every Markdown file under ``corpus_dir`` as a raw chunk.

    Metadata comes from the front-matter block plus file-level defaults.
    """
    pattern = os.path.join(corpus_dir, "**", "*.md")
    raw: List[Chunk] = []
    for path in sorted(glob.glob(pattern, recursive=True)):
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        metadata = parse_front_matter(text)
        if "---" in text:
            # Strip the front matter so it never becomes chunk text.
            text = _FRONT_MATTER_RE.sub("", text, count=1)
        metadata.setdefault("source_doc", os.path.basename(path))
        metadata.setdefault("doc_id", slugify(metadata["source_doc"]))
        metadata.setdefault("category", "knowledge")
        metadata.setdefault("model", "all")
        metadata.setdefault("doc_date", "2026-01-01")
        raw.append(Chunk(text=text.strip(), metadata=dict(metadata)))
    return raw


def split_sections(text: str) -> List[tuple]:
    """Split document text into (section_title, body) pairs.

    The heading line is included in the body so distinctive tokens living in a
    heading (error codes, model names) are part of the retrievable chunk.
    Unheaded prose is folded into an implicit "Introduction" section so no
    content is dropped.
    """
    matches = list(_HEADING_RE.finditer(text))
    sections: List[tuple] = []
    if not matches:
        return [("", text.strip())]

    if matches[0].start() > 0:
        sections.append(("Introduction", text[: matches[0].start()].strip()))

    for i, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = f"## {title}\n{text[start:end]}".strip()
        if body.strip():
            sections.append((title, body))
    return sections


def _chunk_text(body: str, size: int, overlap: int) -> List[str]:
    """Split long section bodies into overlapping fixed-size pieces."""
    words = body.split()
    if len(words) <= size:
        return [body]
    step = max(size - overlap, 1)
    pieces = []
    for i in range(0, len(words), step):
        piece = " ".join(words[i : i + size])
        if piece:
            pieces.append(piece)
    return pieces


def chunk_documents(documents: List[Chunk], config: RAGConfig) -> List[Chunk]:
    """Chunk raw documents into retrieval units.

    Sections are preserved when they fit within ``chunk_size``; oversized
    sections are split with ``chunk_overlap``. Metadata is inherited from the
    document and extended with the section title and chunk index.
    """
    out: List[Chunk] = []
    for doc in documents:
        sections = split_sections(doc.text)
        chunk_index = 0
        for title, body in sections:
            for piece in _chunk_text(body, config.chunk_size, config.chunk_overlap):
                metadata = dict(doc.metadata)
                metadata["section"] = title or "Introduction"
                metadata["chunk_index"] = chunk_index
                metadata["chunk_id"] = f"{doc.doc_id}#{chunk_index}"
                out.append(Chunk(text=piece, metadata=metadata))
                chunk_index += 1
    return out


def load_and_chunk(corpus_dirs: Optional[List[str]], config: RAGConfig) -> List[Chunk]:
    """Convenience wrapper: load + chunk all configured corpus directories."""
    dirs = corpus_dirs if corpus_dirs else config.corpus_dirs
    raw: List[Chunk] = []
    for corpus_dir in dirs:
        raw.extend(load_documents(corpus_dir))
    return chunk_documents(raw, config)
