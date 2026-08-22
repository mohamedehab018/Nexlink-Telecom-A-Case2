"""Outage-specific API endpoints."""
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Any
from shared.outage_persistence import OutageRepository
from shared.checkpointing import CheckpointStore, load_checkpoint
from graphs.outage import OutageWorkflow
from mcp_server.outage_tools import execute_outage_tool


router = APIRouter()

# Initialize shared components
ROOT = Path(__file__).resolve().parents[2]
DB = str(ROOT / 'db' / 'nexlink.db')
repo = OutageRepository(DB)
store = CheckpointStore(DB)
workflow = OutageWorkflow(store, execute_outage_tool, repository=repo)


class IncidentIn(BaseModel):
    """Model for creating an outage incident."""
    account_id: int = Field(gt=0)
    symptoms: list[str] = Field(min_length=1)
    incident_id: Optional[str] = None


class DecisionIn(BaseModel):
    """Model for HITL decision."""
    actor_id: str = Field(min_length=1)
    status: str
    notes: str = ""
    modification: Optional[dict[str, Any]] = None


class FieldIn(BaseModel):
    """Model for field result."""
    resolved: bool


class ResolveIn(BaseModel):
    """Model for ticket resolution."""
    actor_id: str = Field(min_length=1)
    notes: str = ""


def state_or_404(thread_id: str) -> dict:
    """Get state or raise 404."""
    s = repo.state(thread_id) or load_checkpoint(store, thread_id)
    if not s:
        raise HTTPException(404, "unknown outage run")
    return s


@router.post("/outages", status_code=201)
def create_incident(body: IncidentIn):
    """Create a new outage incident."""
    incident = body.incident_id or f'inc-{uuid4().hex[:12]}'
    s = workflow.advance(workflow.start(incident, body.account_id, body.symptoms))
    return s


@router.get("/outages")
def list_incidents():
    """List all outage incidents."""
    return repo.list_incidents()


@router.get("/outages/{thread_id}")
def get_incident(thread_id: str):
    """Get outage incident details."""
    s = state_or_404(thread_id)
    return {
        **s,
        'hypotheses': repo.hypotheses(thread_id),
        'tool_history': repo.tool_history(thread_id),
        'checkpoints': store.history(thread_id),
        'hitl_task': repo.hitl(s['hitl_request_id']) if s.get('hitl_request_id') else None,
        'failure_ticket': repo.ticket(s['failure_ticket_id']) if s.get('failure_ticket_id') else None
    }


@router.get("/outages/{thread_id}/history")
def get_history(thread_id: str):
    """Get outage history (tools + checkpoints)."""
    return {
        'tools': repo.tool_history(thread_id),
        'checkpoints': store.history(thread_id)
    }


@router.post("/outages/{thread_id}/hitl")
def decide_hitl(thread_id: str, body: DecisionIn):
    """Make HITL decision on outage."""
    try:
        return workflow.decide_human_action(
            state_or_404(thread_id),
            body.actor_id,
            body.status,
            body.notes,
            body.modification
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/outages/{thread_id}/field-result")
def field_result(thread_id: str, body: FieldIn):
    """Report field result."""
    return workflow.field_result(state_or_404(thread_id), body.resolved)


@router.get("/hitl-tasks")
def list_hitl_tasks():
    """List all HITL tasks."""
    return repo.hitls()


@router.get("/failure-tickets")
def list_failure_tickets():
    """List all failure tickets."""
    return repo.tickets()


@router.post("/failure-tickets/{ticket_id}/investigate")
def investigate_ticket(ticket_id: str, body: ResolveIn):
    """Investigate a failure ticket."""
    if not repo.ticket(ticket_id):
        raise HTTPException(404, "unknown ticket")
    try:
        repo.investigate_ticket(ticket_id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return repo.ticket(ticket_id)


@router.post("/failure-tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: str, body: ResolveIn):
    """Resolve a failure ticket and resume graph."""
    t = repo.ticket(ticket_id)
    if not t:
        raise HTTPException(404, "unknown ticket")
    try:
        repo.resolve_ticket(ticket_id, body.model_dump())
        return workflow.resume_failure(state_or_404(t['thread_id']))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
