# planning_eval — evaluation harness (Person 2 scope)

The `planning_eval/` folder required by the brief. It contains the test-case
suite, the real incident bundles, the method-comparison runner and the JSON
run traces.

| File | What it does |
| --- | --- |
| `test_cases.py` | `GENERIC_CASES` (keyword problems, ungrounded baseline) + `SCENARIO_CASES` (the real incident bundles, grounded) |
| `scenarios.py` | The real, recurring support-staff requests (dispatch / remote-fix / credit bundles) with the expected resolution per bundle |
| `evaluate_planning.py` | Runs every planning method on every case, records calls / tokens / cost / latency / routing, saves `artifacts/run-*.json`, and falls back to deterministic canned decisions when `GROQ_API_KEY` is absent |
| `run_demo.py` | Regenerates `demo.md`, the runnable demo transcript (offline, deterministic) |
| `demo.md` | Demo transcript: divergence case, one sub-task per method, Self-Refine, Reflexion, grounded-vs-keyword |
| `artifacts/` | Saved `run-*.json` traces, one per evaluation run |

## Run it

Live (requires `GROQ_API_KEY` in `.env`, `GROQ_TPM` optional):

```bash
python planning_eval/evaluate_planning.py
```

Offline / deterministic (no API key):

```bash
GROQ_API_KEY= python planning_eval/evaluate_planning.py
```

Output: a per-case line per method, a FINAL SUMMARY (success rate, avg score,
latency, calls, cost per method), the ROUTING vs OUTCOME section, and the path
of the saved `artifacts/run-*.json` trace. Console `httpx`/`groq` logs are
noise — read the summary and the artifact.

## How scoring works

- Keyword cases are scored by `NexlinkEnvironment` (the model's own terms are
  the only signal) — the cheap ungrounded baseline.
- Scenario bundles are scored by `GroundedEnvironment`, which **executes** the
  proposal's write against the real DB + auth gate: a correct write that
  succeeds = 1.0, a correct decision whose write failed = 0.5, a wrong decision
  that still executed = 0.3 (that is the `$150` truck-roll), a wrong decision
  that failed = 0.1.
- The two decomposition rows are scored by **plan execution** instead, because
  the environment would otherwise re-run the write itself and hide a stale DAG:
  decomposition-first's resolution only counts if the plan's *own* write
  succeeded, otherwise it is "correct decision, write failed" = 0.5. That is
  what makes the divergence visible in the table (see `planning/README.md`).

## Tests

The harness's own tests live in `planning/tests/`
(`test_{routing,grounded_environment,cost}.py`) and run with the rest of the
suite:

```bash
python -m pytest planning/tests -v
```
