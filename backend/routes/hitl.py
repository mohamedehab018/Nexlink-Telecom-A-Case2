"""Unified HITL API endpoints.

Covers all graph types (order_activation, outage, ...) through the shared
SqliteHITLStore.  Two endpoints:

  GET  /api/hitl/tasks              — list tasks (filterable by status/graph/account)
  POST /api/hitl/tasks/{task_id}/decide — approve / reject / modify a pending task

For order_activation tasks that carry a ``run_id``, a successful decision
automatically triggers ``ActivationGraph.resume_after_hitl(run_id)`` so the
graph continues without a separate resume call.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from shared.hitl.store import SqliteHITLStore, PENDING
from shared.hitl.contract import HumanDecision
from graphs.order_activation.graph import ActivationGraph

router = APIRouter()

# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DB = str(ROOT / "db" / "nexlink.db")

_store = SqliteHITLStore(DB)
_graph = ActivationGraph(DB)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class DecideIn(BaseModel):
    """Body for POST /tasks/{task_id}/decide."""

    actor_id: str = Field(min_length=1, description="ID of the admin making the decision")
    status: str = Field(description="One of: approved, rejected, modified")
    notes: str = Field(default="", description="Optional notes / rejection reason")
    modification: Optional[dict[str, Any]] = Field(
        default=None,
        description="Required when status=='modified': key-value overrides merged into the task payload",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task_or_404(task_id: str) -> dict:
    """Return a raw store row or raise HTTP 404."""
    row = _store.task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"HITL task '{task_id}' not found")
    return row


def _format_task(row: dict) -> dict:
    """Return a clean public representation of a hitl_tasks row."""
    import json

    action = json.loads(row["action_json"]) if row.get("action_json") else {}
    decision = json.loads(row["decision_json"]) if row.get("decision_json") else None

    return {
        "task_id": row["task_id"],
        "graph_type": row.get("graph_type"),
        "thread_id": row.get("thread_id"),
        "run_id": row.get("run_id"),
        "account_id": row.get("account_id"),
        "task_type": row.get("task_type"),
        "status": row["status"],
        "description": action.get("description", ""),
        "decision": decision,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/tasks", summary="List HITL tasks")
def list_tasks(
    status: Optional[str] = Query(default=None, description="Filter by status: pending, approved, rejected, modified"),
    graph_type: Optional[str] = Query(default=None, description="Filter by graph type: order_activation, outage, ..."),
    account_id: Optional[int] = Query(default=None, description="Filter by account ID"),
) -> list[dict]:
    """Return all HITL tasks, optionally filtered.

    Query parameters are all optional and can be combined:
    - **status**: ``pending``, ``approved``, ``rejected``, ``modified``
    - **graph_type**: ``order_activation``, ``outage``, ``sla_dispute``
    - **account_id**: integer account identifier
    """
    rows = _store.tasks(status=status, graph_type=graph_type, account_id=account_id)
    return [_format_task(r) for r in rows]


@router.post("/tasks/{task_id}/decide", summary="Approve / reject / modify a HITL task")
def decide_task(task_id: str, body: DecideIn) -> dict:
    """Commit a human decision on a pending HITL task.

    - Returns **HTTP 404** if the task does not exist.
    - Returns **HTTP 409** if the task is no longer pending (already decided).
    - Returns **HTTP 422** if the body fields are invalid (e.g. missing
      ``modification`` for a ``modified`` decision).

    For ``order_activation`` tasks that carry a ``run_id``, the graph is
    automatically resumed after a successful decision and the resume result is
    embedded in the response under ``"resume_result"``.
    """
    row = _task_or_404(task_id)

    if row["status"] != PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"HITL task '{task_id}' has already been decided (status: {row['status']})",
        )

    # Build and validate the decision object
    try:
        decision = HumanDecision(
            status=body.status,
            actor_id=body.actor_id,
            notes=body.notes,
            modified_payload=body.modification,
        )
        _store.commit_decision(task_id, decision)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Re-fetch the updated row
    updated_row = _store.task(task_id)
    response: dict[str, Any] = {
        "task": _format_task(updated_row),
        "message": f"Task '{task_id}' {body.status} by {body.actor_id}",
        "resume_result": None,
    }

    # Auto-resume for order_activation tasks that have a paused run_id
    if row.get("graph_type") == "order_activation" and row.get("run_id"):
        try:
            run_id = int(row["run_id"])
            resume = _graph.resume_after_hitl(run_id)
            response["resume_result"] = resume
        except Exception as exc:  # noqa: BLE001 — surface as non-fatal detail
            response["resume_result"] = {"error": str(exc)}

    return response
