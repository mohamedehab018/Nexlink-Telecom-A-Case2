## Retrieval Architecture Evaluation



_Benchmark: 15 domain questions (basic=5, citation=5, multihop=4, metadata_filter=1). Embedder: SentenceTransformerEmbedder. Generator: deterministic extractive._

| Architecture | Task Accuracy | Avg Input Tokens | Avg Output Tokens | Avg Latency (s) |
| --- | --- | --- | --- | --- |
| Naive RAG | 11/15 | 277 | 242 | 0.03s |
| Hybrid (vector + BM25) | 15/15 | 301 | 271 | 0.02s |
| Agentic RAG | 15/15 | 350 | 320 | 0.32s |

### Accuracy by question category

| Category | Naive RAG | Hybrid | Agentic RAG |
| --- | --- | --- | --- |
| basic | 4/5 | 5/5 | 5/5 |
| citation | 3/5 | 5/5 | 5/5 |
| multihop | 3/4 | 4/4 | 4/4 |
| metadata_filter | 1/1 | 1/1 | 1/1 |

### Per-question detail (hybrid vs agentic trace)

| Question | Naive | Hybrid | Agentic |
| --- | --- | --- | --- |
| `basic-1` (basic) | ✓ | ✓ | ✓ |
| `basic-2` (basic) | ✗ | ✓ | ✓ |
| `basic-3` (basic) | ✓ | ✓ | ✓ |
| `basic-4` (basic) | ✓ | ✓ | ✓ |
| `basic-5` (basic) | ✓ | ✓ | ✓ |
| `citation-1` (citation) | ✗ | ✓ | ✓ |
| `citation-2` (citation) | ✓ | ✓ | ✓ |
| `citation-3` (citation) | ✓ | ✓ | ✓ |
| `citation-4` (citation) | ✓ | ✓ | ✓ |
| `citation-5` (citation) | ✗ | ✓ | ✓ |
| `multihop-1` (multihop) | ✓ | ✓ | ✓ |
| `multihop-2` (multihop) | ✓ | ✓ | ✓ |
| `multihop-3` (multihop) | ✗ | ✓ | ✓ |
| `multihop-4` (multihop) | ✓ | ✓ | ✓ |
| `filter-1` (metadata_filter) | ✓ | ✓ | ✓ |

## Why We Ship Hybrid Search



See README.md for the production justification derived from this table.