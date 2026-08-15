# Planning Agent — Task Decomposition & DAG Engine

**Owner:** Person 1 (Decomposition & DAG Engine). Built on the forked reference
toolkit in [`planning_lab/`](planning_lab/) (`AmrSheta22/task_decomposition_and_planning`,
credited in [`README.upstream.md`](README.upstream.md)) and wired into the
**real** Nexlink MCP server, database and auth gate.

## The planning problem (why it is real)

The memory/RAG agent owns front-desk triage and knowledge-base questions. This
lab's agent owns a different, real pain point: **incident-resolution bundles**.
Support staff send a request like

> "Ellen Ripley has a solid red LED and drops every thunderstorm, equipment log
> shows a hardware fault, she wants a technician out. Resolve the incident."

That bundle is not a single tool call and not a single LLM turn:

- It needs reads (account, equipment, tickets) in dependency order.
- It needs a **judgement** about the resolution (dispatch vs remote fix vs
  credit) that depends on intermediate observations (is the line really dead,
  or is the modem healthy?).
- It ends in a **high-stakes authenticated write** (`$150` technician dispatch,
  billing credit with a `>$25` supervisor gate). A wrong plan has a real cost.
- Every write is gated by `mcp_server/auth.py` session verification whose state
  is **only knowable at runtime** — whether the session is still verified is
  invisible to the planner. That is the genuine ambiguity that makes the two
  decomposition methods diverge.

## Task 1 scope: decomposition into a DAG, both methods

| Concern | Where | What it does |
| --- | --- | --- |
| DAG substrate + **acyclicity at construction** | `planning_lab/models.py` (`Plan.validate_dag`, `Plan.graph/topological_order/execution_batches/terminal_tasks`) | Rejects duplicate ids, unknown deps, self-deps and cycles **before** anything runs; `networkx` topological sort schedules parallel-safe batches |
| Node tool-binding | `planning_lab/models.py` (`Task.kind/tool/args`) | A node can name a real MCP tool; binding is validated at construction |
| **Decomposition-first** | `planning_lab/algorithms/decomposition.py` (`decompose_goal`, `execute_plan`) | One structured call generates the whole DAG up front; tool nodes run through the real executor, LLM runs reasoning nodes, parallel batches preserved |
| **Dynamic/interleaved** | `planning_lab/algorithms/dynamic_decomposition.py` (`dynamic_decomposition`) | Next sub-task is decided after observing the previous real result; a runtime failure reshapes what comes next |
| **Real MCP tools** | `mcp_tools.py` (`MCPToolExecutor`) | Same handlers, same `db/` database, same `auth` gate, same input schemas as the live server — including the real `SECURITY ERROR` a write returns for an unverified session |
| Real staff requests | `planning_eval/scenarios.py` | Recurring Nexlink bundles used by the demo and the eval suite |

The executor deliberately does **not** rebuild the toolkit's scheduling: it
keeps the upstream `Plan`/`Task` models, the networkx topological batches, and
the ThreadPoolExecutor for independent LLM nodes, and only replaces the node
execution target (real MCP tool instead of a generic prompt).

## The divergence case (real numbers)

Same request, same real database, same real auth gate — two isolated sessions:

| Method | Task success | LLM calls | Tool calls | Approx tokens |
| --- | --- | --- | --- | --- |
| Decomposition-first | **No** (write rejected: `SECURITY ERROR`) | 2 | 2 | ~522 |
| Dynamic decomposition | **Yes** (observed the failure, inserted `verify_account_identity`, re-attempted the write) | 5 | 4 | ~2,322 |

Decomposition-first commits to the whole DAG up front. Its plan assumed the
session was already verified (as it is after a prior turn of a live support
conversation); on a fresh session the write node hits the real auth-gate
`SECURITY ERROR`, and the plan **blindly executes the rest of the stale DAG
anyway** — the incident is not resolved. Dynamic decomposition observes the
failed write, reshapes the next sub-task into `verify_account_identity`
(supplying the staff's PIN), re-attempts the write, and resolves the incident.
It pays more calls/tokens — the table, not a guess, is what buys the resolve.

Reproduce with:

```bash
python -m pytest planning/tests -v
```

The exact audit trail (tool, args, result per call) is on
`MCPToolExecutor.call_log` and is asserted in
`tests/test_divergence.py::test_divergence_trace_is_auditable`:
`get_equipment_diagnostics -> schedule_technician_dispatch (SECURITY ERROR) ->
verify_account_identity -> schedule_technician_dispatch (SUCCESS)`.

## Scope for the other owners

Three people, each writing real code (GitHub issues + linked PRs, one owner
each). Person 1 owns this document; the sections below track the merge state.

### Person 2 — planning algorithms + routing (done)

Merged into `planning/` and reviewed; see `README.upstream.md` for
the fork-status of each module. Delivered:

| Concern | Where | What it does |
| --- | --- | --- |
| Plan-and-Solve | `planning_lab/algorithms/plan_and_solve.py` | Explicit plan phase, then solution phase (Groq-compatible `llm.invoke`) |
| Tree-of-Thoughts | `planning_lab/algorithms/tree_of_thoughts.py` | Generate/evaluate beam search; parse failures no longer silently swallowed |
| LATS (grounded) | `planning_lab/algorithms/lats.py` | MCTS with environment feedback + model self-score (`_estimate_value`), 0.75/0.25 backprop |
| LATS (ungrounded control) | `planning_lab/algorithms/lats_ungrounded.py` | Same loop, model self-score as pseudo-feedback, no environment |
| Real feedback | `planning_lab/algorithms/environment.py` (`GroundedEnvironment`) | Executes the proposal's write through the real MCP executor + auth gate; correct write = 1.0, correct decision failed write = 0.5, wrong executed write = 0.3, wrong failed = 0.1 |
| Routing | `routing.py` (`route_subtask`) | Linear sub-tasks → Plan-and-Solve; external-validation sub-tasks → LATS; else ToT; defaults to Plan-and-Solve |
| Cost accounting | `cost.py` (`TrackingLLM`) | Tracks calls + input/output chars, `estimate_cost` against Groq pricing |
| Evaluation | `planning_eval/evaluate_planning.py` + `planning_eval/test_cases.py` | Generic keyword cases + real scenario bundles (grounded); records routing, tokens, cost, latency; saves `planning_eval/artifacts/run-*.json`; offline fallback when no `GROQ_API_KEY` |
| Tests | `tests/test_{plan_and_solve,tree_of_thoughts,lats,grounded_environment,routing}.py` | Deterministic offline via `ScriptedLLM` + temp DB |

## Method comparison table

All planning methods run against every applicable case (10 keyword cases +
3 real scenario bundles), scored by `NexlinkEnvironment` for the keyword cases
and by `GroundedEnvironment` (real DB + auth gate) for the bundles. The runner
is `planning_eval/evaluate_planning.py`; it saves the full trace to
`planning_eval/artifacts/run-*.json`.

Source: offline deterministic run
[`planning_eval/artifacts/run-20260815T184546Z.json`](../planning_eval/artifacts/run-20260815T184546Z.json)
(no API key, so `LLM calls`/`est. cost` are 0; the offline pipeline is
reproducible). With `GROQ_API_KEY` set, the same run fills in real calls /
tokens / latency / cost per method:

```bash
python planning_eval/evaluate_planning.py            # all methods, live API
python planning_eval/evaluate_planning.py DECOMPOSITION_FIRST,DYNAMIC   # subset
```

| Method | Success rate | Avg score | Avg latency | LLM calls | est. cost |
| --- | --- | --- | --- | --- | --- |
| Plan-and-Solve (PS) | 76.9% | 0.843 | 0.012s | 0 | $0.00 |
| Tree-of-Thoughts | 23.1% | 0.231 | 0.011s | 0 | $0.00 |
| Grounded LATS | 76.9% | 0.843 | 0.011s | 0 | $0.00 |
| Ungrounded LATS (control) | 46.2% | 0.679 | 0.013s | 0 | $0.00 |
| Decomposition-first | 33.3% | 0.667 | 0.056s | 0 | $0.00 |
| Dynamic decomposition | 100% | 1.000 | 0.064s | 0 | $0.00 |
| Self-Refine | 100% | 1.000 | 0.052s | 0 | $0.00 |
| Reflexion | 100% | 1.000 | 0.065s | 0 | $0.00 |

Reading the baseline:

- PS and grounded LATS tie on the keyword cases (the cheapest method wins on
  latency); ToT and ungrounded LATS lose because their outputs miss the
  keyword terms, and ungrounded LATS has no real feedback to correct course.
- Decomposition-first, Dynamic, Self-Refine and Reflexion run on the **3
  grounded bundles** only (they need real MCP tools / a real environment).
  The decomposition rows are scored by **plan execution**, not just the final
  decision: the resolution counts only if the plan's *own* write succeeded.
  Decomposition-first commits a stale DAG whose write node skips session
  verification, so its write hits the real `SECURITY ERROR` on the dispatch
  and credit bundles (correct decision, write failed = 0.5) and only the
  no-dispatch bundle resolves -> **1/3 (33%)**. Dynamic decomposition observes
  the failed write, verifies, and re-attempts it -> **3/3 (100%)**. That is
  the divergence, visible in the table. (Cost on the unaffected rows is
  unchanged; a wrong executed write would also score 0.3, the `$150` case.)

### Person 3 — self-correction + grounding + final evidence (in progress)

- `self_refine.py` and `reflexion.py` are adapted to the real sub-task types
  and wired into the eval as `SELF_REFINE` / `REFLEXION` rows (self-refine:
  PS draft + deterministic checks + independent critique; reflexion:
  episodic memory across trials, evaluated against `GroundedEnvironment`).
- Comparison table with all methods on all scenario bundles is above; run the
  eval with `GROQ_API_KEY` set to replace the offline numbers with live
  calls/tokens/cost.
- Demo transcript: `planning_eval/demo.md` (regenerated offline by
  `python planning_eval/run_demo.py`) -- divergence case, one sub-task per
  method, Self-Refine revision, Reflexion cross-trial learning, and the
  grounded-vs-keyword `$150` case.
- TODO: live agent wiring in `agent/planning_agent.py` (currently does not
  import `planning/`).
