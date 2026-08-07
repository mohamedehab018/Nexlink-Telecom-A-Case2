## Retrieval Architecture Evaluation



_Benchmark: 15 domain questions (basic=5, citation=5, multihop=4, metadata_filter=1). Embedder: OfflineEmbedder. Generator: deterministic extractive._

| Architecture | Task Accuracy | Avg Input Tokens | Avg Output Tokens | Avg Latency (s) |
| --- | --- | --- | --- | --- |
| Naive RAG | 13/15 | 281 | 254 | 0.02s |
| Hybrid (vector + BM25) | 14/15 | 309 | 286 | 0.00s |
| Agentic RAG | 15/15 | 326 | 303 | 0.06s |
| Graph RAG (knowledge graph) | 15/15 | 711 | 667 | 0.01s |

### Accuracy by question category

| Category | Naive RAG | Hybrid (vector + BM25) | Agentic RAG | Graph RAG (knowledge graph) |
| --- | --- | --- | --- | --- |
| basic | 5/5 | 5/5 | 5/5 | 5/5 |
| citation | 4/5 | 5/5 | 5/5 | 5/5 |
| multihop | 3/4 | 3/4 | 4/4 | 4/4 |
| metadata_filter | 1/1 | 1/1 | 1/1 | 1/1 |

### Per-question detail

| Question | Naive RAG | Hybrid (vector + BM25) | Agentic RAG | Graph RAG (knowledge graph) |
| --- | --- | --- | --- | --- |
| `basic-1` (basic) | ✓ | ✓ | ✓ | ✓ |
| `basic-2` (basic) | ✓ | ✓ | ✓ | ✓ |
| `basic-3` (basic) | ✓ | ✓ | ✓ | ✓ |
| `basic-4` (basic) | ✓ | ✓ | ✓ | ✓ |
| `basic-5` (basic) | ✓ | ✓ | ✓ | ✓ |
| `citation-1` (citation) | ✓ | ✓ | ✓ | ✓ |
| `citation-2` (citation) | ✓ | ✓ | ✓ | ✓ |
| `citation-3` (citation) | ✓ | ✓ | ✓ | ✓ |
| `citation-4` (citation) | ✓ | ✓ | ✓ | ✓ |
| `citation-5` (citation) | ✗ | ✓ | ✓ | ✓ |
| `multihop-1` (multihop) | ✓ | ✓ | ✓ | ✓ |
| `multihop-2` (multihop) | ✓ | ✓ | ✓ | ✓ |
| `multihop-3` (multihop) | ✓ | ✓ | ✓ | ✓ |
| `multihop-4` (multihop) | ✗ | ✗ | ✓ | ✓ |
| `filter-1` (metadata_filter) | ✓ | ✓ | ✓ | ✓ |

## Why We Ship Hybrid Search



See README.md for the production justification derived from this table.