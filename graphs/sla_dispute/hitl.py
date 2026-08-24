"""LangGraph interrupt boundary for an SLA-dispute approval."""
from typing import Any

from langgraph.types import interrupt

from .hitl_tasks import hitl_task_manager
from .states import SLADisputeState


def is_human_approval_required(state: SLADisputeState) -> bool:
    return state.get("liability_decision") in {"provider", "customer", "shared", "unclear"}


def create_hitl_request(state: SLADisputeState) -> dict[str, Any]:
    """Persist the review task before the interrupt can pause the graph."""
    run_id, customer_id = state.get("run_id"), state.get("customer_id")
    if not run_id or customer_id is None:
        raise ValueError("run_id and customer_id are required before creating a review task.")
    task_id = state.get("hitl_task_id")
    task = hitl_task_manager.get_task(task_id) if task_id else None
    if task is None:
        task = hitl_task_manager.create_task(run_id, customer_id, "sla_dispute_review", "Administrator approval is required before the SLA dispute can be resolved.")
    return {"hitl_task_id": task.task_id, "hitl_required": True, "current_state": "waiting_for_human"}


def request_admin_decision(state: SLADisputeState) -> dict[str, Any]:
    run_id, customer_id = state.get("run_id"), state.get("customer_id")
    if not run_id or customer_id is None:
        raise ValueError("run_id and customer_id are required before requesting a decision.")
    task_id = state.get("hitl_task_id")
    task = hitl_task_manager.get_task(task_id) if task_id else None
    if task is None:
        raise ValueError("A persisted HITL task is required before requesting a decision.")
    decision = interrupt({"type": "sla_dispute_review", "task_id": task.task_id, "run_id": run_id, "customer_id": customer_id, "claim_details": state.get("claim_details"), "liability_decision": state.get("liability_decision"), "liability_reasoning": state.get("liability_reasoning"), "allowed_decisions": ["approve", "reject"]})
    if not isinstance(decision, str) or decision.strip().lower() not in {"approve", "reject"}:
        raise ValueError("Invalid HITL response. Expected approve or reject.")
    normalized = decision.strip().lower()
    if task.status == "pending":
        task = hitl_task_manager.approve(task.task_id) if normalized == "approve" else hitl_task_manager.reject(task.task_id)
    elif task.decision != normalized:
        raise ValueError("Submitted decision conflicts with persisted HITL task.")
    return {"hitl_task_id": task.task_id, "admin_decision": normalized, "hitl_required": False, "current_state": "human_approved" if normalized == "approve" else "human_rejected", "error": None if normalized == "approve" else "SLA dispute resolution was rejected by the administrator."}
