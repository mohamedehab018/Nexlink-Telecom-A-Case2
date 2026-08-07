"""Self-RAG-style checks for recalled memories before they enter an LLM prompt."""
from __future__ import annotations

import re
from .models import VerificationResult


def verify_memory_recall(query: str, evidence: str, claim: str | None = None) -> VerificationResult:
    terms = {x.lower() for x in re.findall(r"[a-zA-Z]{3,}", query)}
    evidence_terms = {x.lower() for x in re.findall(r"[a-zA-Z]{3,}", evidence)}
    overlap = len(terms & evidence_terms) / max(len(terms), 1)
    if overlap < 0.2:
        return VerificationResult(False, "Retrieved memory was withheld: insufficient relevance.", round(overlap, 2))
    if claim:
        claim_terms = {x.lower() for x in re.findall(r"[a-zA-Z]{3,}", claim)}
        unsupported = claim_terms - evidence_terms
        if unsupported:
            return VerificationResult(False, "Retrieved memory was withheld: proposed claim is not supported by evidence.", round(overlap, 2))
    return VerificationResult(True, "Retrieved memory is relevant and supported by its evidence.", round(overlap, 2))
