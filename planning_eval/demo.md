# Nexlink planning agent -- demo transcript

A live walkthrough of the planning lab: decomposition, the planning methods, self-
refinement, reflexion, and grounded feedback. Every line below was produced by
running this repository offline (no API key) against a seeded copy of the real
Nexlink database; the model is a deterministic stand-in for Groq.

Reproduce: `python planning_eval/run_demo.py`  (regenerates this file).

Scoring: `GroundedEnvironment` verifies the session and executes the proposal's
write through the real MCP handlers and auth gate (correct write = 1.0, correct
decision failed write = 0.5, wrong executed write = 0.3, wrong failed = 0.1).

## Part A — the divergence case: decomposition-first vs dynamic

Same staff request (Ellen Ripley, dispatch bundle), same real database, two
isolated sessions. The planner assumes the session was verified in a previous
turn; a fresh session is not.

**Staff request:**
> Ellen Ripley (account 3) has a solid red LED on the Coax-V2 and drops every thunderstorm. Equipment log shows a hardware fault. She wants a technician out this week. Resolve the incident.

### A1. Decomposition-first (stale DAG)
`3`-node plan planned up front: diag, write, summary

Real tool trace (MCP executor call log):
- `get_account_summary({'account_id': 3})` -> `--- Account Summary (ID: 3) --- Customer: Ellen Ripley Address: LV-426 Nostromo Ave, Seattle Plan: Standard ($35.00/mo, up to 50 Mbps)`
- `get_equipment_diagnostics({'account_id': 3})` -> `--- Equipment Diagnostics for Account #3 --- Serial: SN-99X-002 Model: Nextlink-Coax-V2 Status: ERROR Last Log: 2026-07-28 18:45:12 - CRIT_E ...`
- `list_support_tickets({'account_id': 3})` -> `--- Support Tickets for Account #3 (1 total) --- Ticket #2 [TECHNICAL] - Status: OPEN Created: 2026-08-15 18:46:33 Description: Customer com ...`
- `get_equipment_diagnostics({'account_id': 3})` -> `--- Equipment Diagnostics for Account #3 --- Serial: SN-99X-002 Model: Nextlink-Coax-V2 Status: ERROR Last Log: 2026-07-28 18:45:12 - CRIT_E ...`
- `schedule_technician_dispatch({'account_id': 3, 'description': 'Resolve the hardware fault.'})` -> `SECURITY ERROR: Account #3 not verified in this session.`

Write node result: `SECURITY ERROR: Account #3 not verified in this session.`
**Incident resolved: False** -- the stale DAG executes its write without
verification, the auth gate rejects it, and the rest of the plan runs anyway.

### A2. Dynamic decomposition (adapts)
Real tool trace (MCP executor call log):
- `get_account_summary({'account_id': 3})` -> `--- Account Summary (ID: 3) --- Customer: Ellen Ripley Address: LV-426 Nostromo Ave, Seattle Plan: Standard ($35.00/mo, up to 50 Mbps)`
- `get_equipment_diagnostics({'account_id': 3})` -> `--- Equipment Diagnostics for Account #3 --- Serial: SN-99X-002 Model: Nextlink-Coax-V2 Status: ERROR Last Log: 2026-07-28 18:45:12 - CRIT_E ...`
- `list_support_tickets({'account_id': 3})` -> `--- Support Tickets for Account #3 (1 total) --- Ticket #2 [TECHNICAL] - Status: OPEN Created: 2026-08-15 18:46:33 Description: Customer com ...`
- `get_equipment_diagnostics({'account_id': 3})` -> `--- Equipment Diagnostics for Account #3 --- Serial: SN-99X-002 Model: Nextlink-Coax-V2 Status: ERROR Last Log: 2026-07-28 18:45:12 - CRIT_E ...`
- `schedule_technician_dispatch({'account_id': 3, 'description': 'Resolve the hardware fault.'})` -> `SECURITY ERROR: Account #3 not verified in this session.`
- `verify_account_identity({'account_id': 3, 'account_pin': 9999})` -> `VERIFICATION SUCCESSFUL: Session authorized for Account #3.`
- `schedule_technician_dispatch({'account_id': 3, 'description': 'Resolve the hardware fault.'})` -> `SUCCESS: Technician dispatch scheduled for Account #3. Ticket ID: #3 Address: LV-426 Nostromo Ave, Seattle Status: OPEN Description: Resolve ...`

The planner observes the failed write, inserts `verify_account_identity`
(staff PIN via the credential provider), and re-attempts the write.
**Incident resolved: True.**

Same decision, same tools, same database -- the difference is *when* the plan is
committed. The trade (extra calls/tokens for the reshape) is measured in
`tests/test_divergence.py` and in the comparison table.

---

## Part B — one sub-task solved by each planning method

Shared sub-task: resolve the Ellen Ripley incident (hardware fault, dispatch needed),
scored by the real grounded environment. Each method gets an isolated session.

| Method | Output (excerpt) | Grounded score | Success | Tool calls |
| --- | --- | --- | --- | --- |
| Plan-and-Solve | `Dispatch a technician to resolve the hardware fault.` | 1.0 | True | 5 |
| Tree-of-Thoughts | `Dispatch a technician to replace the faulty modem.` | 1.0 | True | 7 |
| LATS (grounded) | `Dispatch a technician to resolve the hardware fault.` | 1.0 | True | 7 |
| LATS (ungrounded) | `Dispatch a technician to resolve the hardware fault.` | 1.0 | True | 5 |

Grounded LATS pays a few extra tool calls because it generates and *evaluates*
candidate actions against the real system before committing; Plan-and-Solve
commits directly. Both resolve the incident here.

---

## Part C — Self-Refine: a draft is critiqued and revised

Draft: `No dispatch needed; resolve the issue remotely.`

Deterministic checks (grounded, no LLM):
- The deliverable is under 80 words and is probably incomplete.
- The deliverable has no visible structure (headings or list items).

Independent critic: *The draft is too short to be actionable: it does not state the account, the hardware evidence, or the dispatch decision.*

Revised: `Dispatch a technician to resolve the hardware fault.`

Grounded score of revised output: **1.0 (resolved)** vs 0.3 for the unrevised draft.

---

## Part D — Reflexion: learning across trials

Trials: 2

- **Trial 1** attempt: `No dispatch needed; resolve the issue remotely.` -> score 0.3 (NOT resolved)
  - Reflection (episodic memory): I chose a remote fix without confirming the equipment log was healthy; next trial I will schedule the technician dispatch.
- **Trial 2** attempt: `Dispatch a technician to resolve the hardware fault.` -> score 1.0 (resolved)

Final: `Dispatch a technician to resolve the hardware fault.` -- success=True

Memory carried into the next trial: `I chose a remote fix without confirming the equipment log was healthy; next trial I will schedule the technician dispatch.`

The wrong first decision (remote fix on a hardware fault) was rejected by the
grounded environment; the stored lesson redirected the second attempt.

---

## Part E — grounded beats keyword scoring: the $150 case

The SAME proposal, scored two ways, on the Walter White outage bundle
(diagnostics say the line is healthy -> no dispatch).
Proposal: `Diagnose the connection issue, then dispatch a technician to the customer site.`

- **Ungrounded (`NexlinkEnvironment`)**: score **0.875** -> success=True. It contains the words 'diagnose', 'connection' and
  'technician', so the keyword check approves it.
- **Grounded (`GroundedEnvironment`)**: score **0.3** -> success=False. It actually schedules the technician dispatch
  against the real DB -- an unnecessary ~$150 truck-roll for a healthy line.

Details: decision=dispatch_required | expected=no_dispatch_required | VERIFICATION SUCCESSFUL: Session authorized for Account #2. | SUCCESS: Technician dispatch scheduled for Account #2. |   Ticket ID: #3 |   Address: 308 Negra Arroyo Lane, Albuquerque |   Status: OPEN |   Description: Resolve incident. | writes_in_call_log=1

---
