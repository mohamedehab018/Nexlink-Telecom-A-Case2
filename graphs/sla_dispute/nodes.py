"""Deterministic SLA-dispute analysis nodes.

The graph reads account data through the existing MCP database module and uses
the repository's RAG policy corpus when available; neither path is required for
the workflow to give an auditable human-review result.

LLM-call additions inside named nodes (two of the four allowed techniques):

* RAG architecture — ``store_sla_evidence``: retrieves the applicable credit /
  SLA policy clauses from the shared vector store instead of hardcoding one
  file, so liability is grounded in the terms that match this claim.
* Tree of Thoughts — ``select_root_cause``: every candidate root cause is a
  branch; the LLM scores each branch against the claim evidence before one is
  selected, because a wrong root cause flips liability.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from graphs.llm_additions import chat_json
from mcp_server.db import create_support_ticket, get_account_summary, get_equipment_by_account, list_support_tickets

from .states import SLADisputeState


def _candidates(claim: str) -> list[str]:
    return [
        f"Provider network outage or infrastructure failure: {claim[:180]}",
        f"Customer-premises equipment or cabling fault: {claim[:180]}",
        f"Shared responsibility or insufficient evidence: {claim[:180]}",
    ]


def _policy_evidence() -> list[str]:
    policy = Path(__file__).resolve().parents[2] / "rag" / "corpus" / "policies" / "service_credit_policy.md"
    if policy.exists():
        return [policy.read_text(encoding="utf-8", errors="ignore")[:1500]]
    return ["Service credits may apply when downtime exceeds the SLA threshold; supervisor approval is required."]


def receive_dispute(state: SLADisputeState) -> dict[str, Any]:
    if not state.get("run_id") or state.get("customer_id") is None or not state.get("claim_details", "").strip():
        raise ValueError("run_id, customer_id and SLA dispute details are required.")
    return {"current_state": "dispute_received", "error": None, "hitl_required": False}


def analyze_dispute(state: SLADisputeState) -> dict[str, Any]:
    claim = state["claim_details"].strip()
    evidence: list[str] = []
    try:
        account = get_account_summary(state["customer_id"])
        if account:
            evidence.append(f"Account: {account}")
        evidence += [f"Equipment: {item}" for item in get_equipment_by_account(state["customer_id"])[:2]]
        evidence += [f"Ticket: {item}" for item in list_support_tickets(state["customer_id"])[:2]]
    except Exception as exc:
        evidence.append(f"Account enrichment unavailable: {type(exc).__name__}")
    return {"current_state": "dispute_analyzed", "root_cause_candidates": state.get("root_cause_candidates") or _candidates(claim), "root_cause_evidence": evidence, "error": None}


def store_root_cause_candidates(state: SLADisputeState) -> dict[str, Any]:
    candidates = [x.strip() for x in state.get("root_cause_candidates", []) if isinstance(x, str) and x.strip()]
    if not candidates:
        raise ValueError("No root-cause candidates were produced.")
    return {"root_cause_candidates": candidates, "current_state": "root_causes_generated"}


def select_root_cause(state: SLADisputeState) -> dict[str, Any]:
    """LLM addition — Tree of Thoughts over candidate root causes.

    Each candidate is one branch; the LLM scores every branch against the
    claim and the collected evidence, then selects the strongest with an
    explicit rationale. Falls back to the first heuristic candidate when the
    LLM is unavailable so the graph stays runnable offline.
    """
    candidates = state.get("root_cause_candidates", [])
    if not candidates:
        raise ValueError("No root-cause candidates are available.")

    verdict = chat_json(
        system=(
            "You are a telecom SLA-dispute analyst performing Tree of Thoughts "
            "reasoning. You will be given candidate explanations (branches) "
            "for a service complaint plus the account evidence. Score each "
            "branch 0-100 for how well it explains the claim, then select the "
            "best branch. Respond with ONLY a JSON object: "
            '{"branches": [{"branch": <1-based int>, "score": <0-100>, '
            '"note": "<short reason>"}], "selected": <1-based int>, '
            '"reasoning": "<2-3 sentence justification>"}'
        ),
        user=(
            f"CLAIM:\n{state.get('claim_details', '').strip()}\n\n"
            f"EVIDENCE:\n" + "\n".join(state.get("root_cause_evidence", [])[:6]) + "\n\n"
            "CANDIDATE BRANCHES:\n"
            + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(candidates))
        ),
    )

    selected_idx = None
    if verdict:
        try:
            selected_idx = int(verdict.get("selected")) - 1
        except (TypeError, ValueError):
            selected_idx = None
        if selected_idx is None or not (0 <= selected_idx < len(candidates)):
            selected_idx = None

    if selected_idx is None:
        # Deterministic fallback keeps the graph auditable without an LLM.
        return {"selected_root_cause": candidates[0], "current_state": "root_cause_selected"}

    branches = verdict.get("branches") if isinstance(verdict.get("branches"), list) else []
    return {
        "selected_root_cause": candidates[selected_idx],
        "root_cause_reasoning": str(verdict.get("reasoning", "")).strip(),
        "tot_branches": [
            {
                "branch": b.get("branch"),
                "score": b.get("score"),
                "note": b.get("note"),
            }
            for b in branches
            if isinstance(b, dict)
        ],
        "current_state": "root_cause_selected",
    }


_rag_pipeline: Any = None


def _get_rag_pipeline():
    """Lazy, process-wide RAG pipeline over the shared policy corpus."""
    global _rag_pipeline
    if _rag_pipeline is None:
        from rag.config import load_config
        from rag.pipeline import RAGPipeline

        _rag_pipeline = RAGPipeline(config=load_config(), auto_index=True)
    return _rag_pipeline


def store_sla_evidence(state: SLADisputeState) -> dict[str, Any]:
    """LLM addition — RAG architecture node.

    Retrieves the SLA/credit policy chunks that match this specific claim
    from the repository's shared vector store (the same corpus the support
    agent indexes), instead of hardcoding one markdown file. Falls back to
    the static policy file when the store is unavailable.
    """
    documents = state.get("retrieved_documents")
    sla_terms = state.get("sla_terms")
    if not documents:
        try:
            result = _get_rag_pipeline().answer(
                state.get("claim_details", "SLA credit policy"),
                architecture="hybrid",
                verify=False,
            )
            docs = [
                f"[{getattr(c, 'metadata', {}).get('source', 'policy')}] {c.text}"
                for c in getattr(result, "contexts", []) or []
            ]
            if docs:
                documents = docs
                sla_terms = (getattr(result, "answer", "") or "").strip() or docs[0][:400]
        except Exception:
            documents = None  # fall through to the static file below
        if not documents:
            documents = _policy_evidence()
    return {
        "retrieved_documents": documents,
        "sla_terms": sla_terms or documents[0][:400],
        "current_state": "sla_evidence_retrieved",
    }


def determine_liability(state: SLADisputeState) -> dict[str, Any]:
    claim = state.get("claim_details", "").lower()
    cause = state.get("selected_root_cause", "").lower()
    if any(term in claim for term in ("outage", "down", "unavailable")) and "provider" in cause:
        decision, reason = "provider", "Claim and selected cause indicate a provider outage; human approval is required for any credit."
    elif any(term in claim for term in ("router", "modem", "cable")) and "equipment" in cause:
        decision, reason = "customer", "The available claim points to customer-premises equipment; human review is retained."
    else:
        decision, reason = "unclear", "Available evidence does not establish responsibility; human review is required."
    return {"liability_decision": decision, "liability_reasoning": reason, "current_state": "liability_determined"}


def evaluate_hitl_requirement(state: SLADisputeState) -> dict[str, Any]:
    # Credits and liability decisions have financial/customer impact, so review is always explicit.
    return {"hitl_required": True, "current_state": "waiting_for_human"}


def complete_dispute(state: SLADisputeState) -> dict[str, Any]:
    response = state.get("customer_response") or "The SLA dispute has been reviewed and the approved resolution will be applied."
    return {"customer_response": response, "customer_reply": response, "current_state": "completed", "error": None}


def mark_failure(state: SLADisputeState) -> dict[str, Any]:
    return {"current_state": "failed", "error": state.get("error") or "SLA dispute workflow was rejected by the administrator."}


def create_failure_ticket(state: SLADisputeState) -> dict[str, Any]:
    ticket = create_support_ticket(state["customer_id"], "other", f"SLA dispute workflow failed. Run ID: {state['run_id']}. Reason: {state.get('error')}")
    if not ticket or not ticket.get("ticket_id"):
        raise RuntimeError("Failure ticket was not created.")
    return {"failure_ticket_id": ticket["ticket_id"], "current_state": "failure_ticket_created"}
