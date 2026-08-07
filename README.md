# Nexlink-Telecom-A-Technical Support

## The Company & The Problem

**Nextlink** is an Internet Service Provider (ISP) dealing with a high volume of customer support requests. Human agents are currently overwhelmed by routine tasks: diagnosing router LED codes, upgrading/downgrading customer billing tiers, and dispatching field technicians for physical line repairs. 

The core technical problem is bridging the gap between messy, unpredictable inputs and high-stakes database executions:
* **Messy Inputs:** Customers describe hardware failures in non-technical terms ("the dog chewed the white wire"), and routers output unstructured, noisy error logs. Standard deterministic scripts crash trying to parse this data.
* **High-Stakes Actions:** Standard, unconstrained LLMs are too dangerous to trust with billing databases. If an AI hallucinates a  "Free Internet" plan or accidentally dispatches a technical support onsite (just because the router needed a restart), the financial damage is immediate and the support quality suffers.

## The Solution

We built an **MCP (Model Context Protocol) Server** to act as a secure, intelligent bridge between the LLM and the billing/diagnostics database (see `mcp_server/`), plus a **vector-store Retrieval-Augmented Generation (RAG)** layer so the agent answers policy, hardware, and error-code questions from a curated knowledge base instead of from memory (see `rag/`).

## Retrieval Architecture Evaluation

The RAG layer ships three retrieval architectures and a Self-RAG verification gate:

* **Naive RAG** — embed the query and run a single HNSW similarity search.
* **Hybrid search** — vector similarity **and** BM25 keyword search fused with Reciprocal Rank Fusion (RRF). Distinctive identifiers (`ERR-4091`, `Nextlink-Coax-V2`) are treated as atomic tokens and boosted, so exact sections outrank passing mentions.
* **Agentic RAG** — a LangGraph loop that decomposes the query into sub-queries, retrieves, grades each chunk for relevance (Self-RAG style), and re-queries/rewrites until the evidence is strong enough.
* **Self-RAG gate** — post-retrieval relevance + post-generation grounding checks (Groq reflection-token critic, deterministic heuristic fallback). Unsupported answers are blocked or retried rather than surfaced.

Benchmarked against 15 domain questions (`retrieval_eval/questions.json`) using a real `sentence-transformers` embedder and a deterministic extractive generator:

| Architecture | Task Accuracy | Avg Input Tokens | Avg Output Tokens | Avg Latency (s) |
| --- | --- | --- | --- | --- |
| Naive RAG | 11/15 | 277 | 242 | 0.03s |
| Hybrid (vector + BM25) | 15/15 | 301 | 271 | 0.02s |
| Agentic RAG (LangGraph) | 15/15 | 350 | 320 | 0.32s |

Full per-question detail is in `retrieval_eval/results.md`; re-run with
`python retrieval_eval/run_eval.py`.

### Why we ship hybrid search

1. **Naive RAG fails exactly where the assignment predicts.** Pure vector search loses citation-heavy queries ("what does ERR-4091 mean?") because generic terms like *error* and *code* outrank the exact code, and it mis-ranks the LED-table lookups. It only reaches 11/15.
2. **Hybrid search fixes citations at zero extra cost.** BM25 + the identifier bonus surface the exact code section, and RRF fuses the two ranked lists so a good match from either leg survives. 15/15 at 0.02s/query.
3. **Agentic RAG adds capability, not accuracy.** It also reaches 15/15 — including latent multi-hop questions hybrid misses (multihop-4: threshold + error-code lookup) — but at **~10-16x the latency** and more tokens per query.
4. **Routing decision:** the agent defaults to hybrid and the pipeline automatically promotes a query to the agentic loop when Self-RAG verification fails, or when the query shape is clearly multi-hop (multiple error codes/models). This gives 15/15 quality at near-hybrid cost.

## Database Architecture

To execute provisioning and diagnostics, the MCP server connects to a local relational database (SQLite). The schema enforces strict data integrity using `AUTOINCREMENT` integer primary keys, explicit foreign key relations, and strict `CHECK` constraints to emulate Enums for equipment statuses and ticketing.

The database is built and populated using `db/setup_db.py`, which executes:
1. **`schema.sql`**: Defines the strict table boundaries.
2. **`seed.sql`**: Injects varied test scenarios, including active users, users with raw hardware failure syslogs, and open support tickets.

### Entity-Relationship Diagram (ERD)

Everything branches securely off the central `ACCOUNTS` table, ensuring the agent cannot query equipment or manipulate billing without a valid account context.

![Nextlink Database ERD](db/ERD.png)