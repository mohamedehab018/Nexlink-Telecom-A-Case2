# Planning Agent — Task Decomposition & DAG Engine

**Owner:** Person 1 (Decomposition & DAG Engine). Built on the forked reference
toolkit in [`algorithms/`](algorithms/) (`AmrSheta22/task_decomposition_and_planning`,
credited in [`algorithms/README.upstream.md`](algorithms/README.upstream.md)) and wired into the
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
| DAG substrate + **acyclicity at construction** | `algorithms/planning_lab/models.py` (`Plan.validate_dag`, `Plan.graph/topological_order/execution_batches/terminal_tasks`) | Rejects duplicate ids, unknown deps, self-deps and cycles **before** anything runs; `networkx` topological sort schedules parallel-safe batches |
| Node tool-binding | `algorithms/planning_lab/models.py` (`Task.kind/tool/args`) | A node can name a real MCP tool; binding is validated at construction |
| **Decomposition-first** | `algorithms/planning_lab/algorithms/decomposition.py` (`decompose_goal`, `execute_plan`) | One structured call generates the whole DAG up front; tool nodes run through the real executor, LLM runs reasoning nodes, parallel batches preserved |
| **Dynamic/interleaved** | `algorithms/planning_lab/algorithms/dynamic_decomposition.py` (`dynamic_decomposition`) | Next sub-task is decided after observing the previous real result; a runtime failure reshapes what comes next |
| **Real MCP tools** | `mcp_tools.py` (`MCPToolExecutor`) | Same handlers, same `db/` database, same `auth` gate, same input schemas as the live server — including the real `SECURITY ERROR` a write returns for an unverified session |
| Real staff requests | `scenarios.py` | Recurring Nexlink bundles used by the demo and the eval suite |

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

- **Person 2** — planning algorithms: `plan_and_solve.py`, `tree_of_thoughts.py`,
  `lats.py` are forked verbatim under `algorithms/planning_lab/algorithms/`;
  the routing decision will live next to the executor.
- **Person 3** — self-correction + grounding: `self_refine.py`, `reflexion.py`,
  `environment.py` are forked verbatim; the randomized `Environment` default in
  `environment.py` must be replaced with a real feedback source.
