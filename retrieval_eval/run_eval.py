#!/usr/bin/env python3
"""Benchmark runner for the three retrieval architectures.

Loads ``questions.json``, runs every architecture against every question, and
measures:

* **Task Accuracy** -- all ``expected_all`` phrases and at least one of
  ``expected_any`` must appear in the answer (case-insensitive substring).
* **Retrieval hit@k** -- fraction of questions where a ``gold_docs`` document
  appeared among the retrieved chunks (secondary diagnostic).
* **Average input / output tokens** and **latency per query**.

Output is a Markdown comparison table ready to embed in ``README.md``.

Usage::

    python retrieval_eval/run_eval.py                          # extractive (offline)
    python retrieval_eval/run_eval.py --llm                    # Groq LLM answers
    python retrieval_eval/run_eval.py --provider ngram         # force offline embedder
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.config import load_config  # noqa: E402
from rag.pipeline import RAGPipeline  # noqa: E402

ARCH_ORDER = ["naive", "hybrid", "agentic", "graph"]
ARCH_LABELS = {
    "naive": "Naive RAG",
    "hybrid": "Hybrid (vector + BM25)",
    "agentic": "Agentic RAG",
    "graph": "Graph RAG (knowledge graph)",
}


@dataclass
class QuestionResult:
    question_id: str
    category: str
    question: str
    correct: bool
    hit: bool
    input_tokens: int
    output_tokens: int
    latency: float
    answer: str = ""
    retrieved_sources: List[str] = field(default_factory=list)


def _contains_any(answer: str, phrases: List[str]) -> bool:
    lowered = answer.lower()
    return any(p.lower() in lowered for p in phrases)


def evaluate_answer(question: Dict[str, object], answer: str) -> bool:
    all_ok = all(p.lower() in answer.lower() for p in question.get("expected_all", []))
    any_ok = _contains_any(answer, question.get("expected_any", [])) if question.get("expected_any") else True
    return all_ok and any_ok


def gold_doc_hit(question: Dict[str, object], sources: List[str]) -> bool:
    gold = set(question.get("gold_docs", []))
    if not gold:
        return True
    return bool(gold & set(sources))


def run_architecture(
    pipeline: RAGPipeline,
    arch: str,
    questions: List[Dict[str, object]],
) -> List[QuestionResult]:
    results: List[QuestionResult] = []
    runner = pipeline.architectures[arch]
    for q in questions:
        start = time.perf_counter()
        result = runner.answer(q["question"], metadata_filter=q.get("metadata_filter"))
        elapsed = time.perf_counter() - start
        results.append(
            QuestionResult(
                question_id=str(q["id"]),
                category=str(q["category"]),
                question=str(q["question"]),
                correct=evaluate_answer(q, result.answer),
                hit=gold_doc_hit(q, [c.source for c in result.contexts]),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency=elapsed,
                answer=result.answer[:300],
                retrieved_sources=sorted({c.source for c in result.contexts}),
            )
        )
    return results


def format_table(rows: List[QuestionResult]) -> str:
    lines = [
        "| Architecture | Task Accuracy | Avg Input Tokens | Avg Output Tokens | Avg Latency (s) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for arch in ARCH_ORDER:
        subset = [r for r in rows if getattr(r, "architecture", None) == arch]
        if not subset:
            continue
        acc = sum(r.correct for r in subset)
        n = len(subset)
        lines.append(
            f"| {ARCH_LABELS[arch]} | {acc}/{n} | "
            f"{mean(r.input_tokens for r in subset):.0f} | "
            f"{mean(r.output_tokens for r in subset):.0f} | "
            f"{mean(r.latency for r in subset):.2f}s |"
        )
    return "\n".join(lines)


def build_architecture_tagged_rows(
    all_rows: Dict[str, List[QuestionResult]],
) -> List[QuestionResult]:
    flat: List[QuestionResult] = []
    for arch in ARCH_ORDER:
        for r in all_rows.get(arch, []):
            setattr(r, "architecture", arch)
            flat.append(r)
    return flat


def _arch_headers() -> List[str]:
    return [ARCH_LABELS[arch] for arch in ARCH_ORDER]


def per_category_table(all_rows: Dict[str, List[QuestionResult]]) -> str:
    headers = _arch_headers()
    lines = [
        "### Accuracy by question category",
        "",
        f"| Category | {' | '.join(headers)} |",
        f"| --- | {' | '.join(['---'] * len(headers))} |",
    ]
    categories = ["basic", "citation", "multihop", "metadata_filter"]
    for cat in categories:
        cells = []
        for arch in ARCH_ORDER:
            rows = [r for r in all_rows.get(arch, []) if r.category == cat]
            if rows:
                cells.append(f"{sum(r.correct for r in rows)}/{len(rows)}")
            else:
                cells.append("-")
        lines.append(f"| {cat} | {' | '.join(cells)} |")
    return "\n".join(lines)


def detail_table(all_rows: Dict[str, List[QuestionResult]]) -> str:
    headers = _arch_headers()
    lines = [
        "### Per-question detail",
        "",
        f"| Question | {' | '.join(headers)} |",
        f"| --- | {' | '.join(['---'] * len(headers))} |",
    ]
    by_id: Dict[str, List[QuestionResult]] = {}
    for arch in ARCH_ORDER:
        for r in all_rows.get(arch, []):
            by_id.setdefault(r.question_id, []).append(r)
    for qid, rows in by_id.items():
        q = rows[0]
        mark = {arch: ("✓" if _by_arch(rows, arch).correct else "✗") for arch in ARCH_ORDER}
        cells = [mark[arch] for arch in ARCH_ORDER]
        lines.append(f"| `{qid}` ({q.category}) | {' | '.join(cells)} |")
    return "\n".join(lines)


def _by_arch(rows: List[QuestionResult], arch: str) -> QuestionResult:
    for r in rows:
        if getattr(r, "architecture", None) == arch:
            return r
    return rows[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", default=os.path.join(os.path.dirname(__file__), "questions.json"))
    parser.add_argument("--architectures", default=",".join(ARCH_ORDER))
    parser.add_argument("--provider", default=None, help="Embedding provider override")
    parser.add_argument("--llm", action="store_true", help="Use Groq LLM generator (needs GROQ_API_KEY)")
    parser.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "results.md"))
    parser.add_argument("--no-write", action="store_true", help="Print without writing results file")
    args = parser.parse_args()

    with open(args.questions, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    questions: List[Dict[str, object]] = payload["questions"]
    print(f"Loaded {len(questions)} questions from {args.questions}")

    config = load_config()
    if args.provider:
        config.embedding_provider = args.provider

    pipeline = RAGPipeline(config=config, auto_index=False)
    pipeline.reindex()
    print(f"Corpus indexed: {pipeline.corpus_size} chunks "
          f"(embedder={type(pipeline.embedder).__name__}, "
          f"generator={'GroqGenerator' if args.llm else 'ExtractiveGenerator'})")

    arch_names = [a.strip() for a in args.architectures.split(",") if a.strip()]
    all_rows: Dict[str, List[QuestionResult]] = {}
    for arch in arch_names:
        print(f"Running {ARCH_LABELS[arch]} over {len(questions)} questions...")
        start = time.perf_counter()
        all_rows[arch] = run_architecture(pipeline, arch, questions)
        print(f"  done in {time.perf_counter() - start:.1f}s")

    flat = build_architecture_tagged_rows(all_rows)
    summary = format_table(flat)
    by_category = per_category_table(all_rows)
    detail = detail_table(all_rows)

    report = "\n\n".join(
        [
            "## Retrieval Architecture Evaluation",
            "",
            f"_Benchmark: {len(questions)} domain questions "
            f"(basic={sum(1 for q in questions if q['category']=='basic')}, "
            f"citation={sum(1 for q in questions if q['category']=='citation')}, "
            f"multihop={sum(1 for q in questions if q['category']=='multihop')}, "
            f"metadata_filter={sum(1 for q in questions if q['category']=='metadata_filter')}). "
            f"Embedder: {type(pipeline.embedder).__name__}. "
            f"Generator: {'Groq LLM' if args.llm else 'deterministic extractive'}._",
            summary,
            by_category,
            detail,
            "## Why We Ship Hybrid Search",
            "",
            "See README.md for the production justification derived from this table.",
        ]
    )

    print("\n" + "=" * 78)
    print(report)
    if not args.no_write:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"\n[written] {args.output}")
    pipeline.store.close()


if __name__ == "__main__":
    main()
