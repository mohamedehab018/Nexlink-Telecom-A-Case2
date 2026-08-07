"""Shared text-processing helpers for tokenization and query filtering."""

from __future__ import annotations

import re
from typing import List, Set

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# Generic filler terms with little retrieval signal. Distinctive identifiers
# (error codes, model names, numbers) are never dropped.
STOPWORDS: Set[str] = {
    "what", "does", "mean", "how", "which", "do", "why", "should", "can",
    "the", "a", "an", "is", "are", "be", "for", "of", "to", "in", "on",
    "and", "per", "with", "it", "its", "this", "that", "customer", "agent",
    "when", "will", "would", "need", "from", "using", "use", "then", "than",
    "whats", "drops", "report", "reports", "wants", "applies", "error", "errors",
    "code", "codes", "message", "messages", "means", "meaning", "fix", "fixes",
    "tell", "there", "their", "they", "you", "your", "about", "please",
}


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def distinctive_terms(text: str) -> Set[str]:
    """Error codes, hardware models, and numbers found in ``text``."""
    terms: Set[str] = set()
    terms |= set(re.findall(r"\berr-\d{4}\b", text, flags=re.IGNORECASE))
    terms |= set(re.findall(r"\bnextlink-\w+-v\d\b", text, flags=re.IGNORECASE))
    terms |= set(re.findall(r"\b\d+(?:\.\d+)?\b", text))
    return terms


def content_tokens(text: str) -> List[str]:
    """Query-side token filter.

    Keeps distinctive identifiers unconditionally and drops generic filler
    terms so a citation query like "what does error code ERR-4091 mean" is
    driven by ``ERR-4091`` rather than by generic words that also match an
    unrelated intro paragraph.
    """
    tokens = tokenize(text)
    distinct = distinctive_terms(text)
    out = []
    for tok in tokens:
        if tok in STOPWORDS and tok not in distinct:
            continue
        out.append(tok)
    return out
