"""FastAPI platform API for durable outage incidents."""
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from graphs.outage import OutageWorkflow
from shared.checkpointing import CheckpointStore, load_checkpoint
from shared.outage_persistence import OutageRepository
from mcp_server.outage_tools import execute_outage_tool

ROOT=Path(__file__).resolve().parents[1]; DB=str(ROOT/'db'/'nexlink.db')
repo=OutageRepository(DB); store=CheckpointStore(DB)
workflow=OutageWorkflow(store,execute_outage_tool,repository=repo)
app=FastAPI(title='Nextlink Outage Incidents API')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
class IncidentIn(BaseModel): account_id:int=Field(gt=0); symptoms:list[str]=Field(min_length=1); incident_id:str|None=None
class DecisionIn(BaseModel): actor_id:str=Field(min_length=1); status:str; notes:str=''; modification:dict|None=None
class FieldIn(BaseModel): resolved:bool
class ResolveIn(BaseModel): actor_id:str=Field(min_length=1); notes:str=''
def state_or_404(thread_id):
    s=repo.state(thread_id) or load_checkpoint(store,thread_id)
    if not s:raise HTTPException(404,'unknown outage run')
    return s
@app.post('/api/outages',status_code=201)
def create_incident(body:IncidentIn):
    incident=body.incident_id or f'inc-{uuid4().hex[:12]}';s=workflow.advance(workflow.start(incident,body.account_id,body.symptoms));return s
@app.get('/api/outages')
def incidents():return repo.list_incidents()
@app.get('/api/outages/{thread_id}')
def details(thread_id:str):
    s=state_or_404(thread_id); return {**s,'hypotheses':repo.hypotheses(thread_id),'tool_history':repo.tool_history(thread_id),'checkpoints':store.history(thread_id),'hitl_task':repo.hitl(s['hitl_request_id']) if s.get('hitl_request_id') else None,'failure_ticket':repo.ticket(s['failure_ticket_id']) if s.get('failure_ticket_id') else None}
@app.get('/api/outages/{thread_id}/history')
def history(thread_id:str):return {'tools':repo.tool_history(thread_id),'checkpoints':store.history(thread_id)}
@app.post('/api/outages/{thread_id}/hitl')
def decide(thread_id:str,body:DecisionIn):
    try:
        return workflow.decide_human_action(state_or_404(thread_id),body.actor_id,body.status,body.notes,body.modification)
    except ValueError as exc:
        # A repeated/stale admin decision is a normal optimistic-concurrency
        # conflict, not an unhandled server error.
        raise HTTPException(409, str(exc))
@app.post('/api/outages/{thread_id}/field-result')
def field(thread_id:str,body:FieldIn):return workflow.field_result(state_or_404(thread_id),body.resolved)
@app.get('/api/hitl-tasks')
def hitl_tasks():return repo.hitls()
@app.get('/api/failure-tickets')
def tickets():return repo.tickets()
@app.post('/api/failure-tickets/{ticket_id}/investigate')
def investigate(ticket_id:str,body:ResolveIn):
    if not repo.ticket(ticket_id): raise HTTPException(404,'unknown ticket')
    try:
        repo.investigate_ticket(ticket_id,body.model_dump())
    except ValueError as exc: raise HTTPException(409,str(exc))
    return repo.ticket(ticket_id)
@app.post('/api/failure-tickets/{ticket_id}/resolve')
def resolve(ticket_id:str,body:ResolveIn):
    t=repo.ticket(ticket_id)
    if not t:raise HTTPException(404,'unknown ticket')
    try:
        repo.resolve_ticket(ticket_id,body.model_dump())
        return workflow.resume_failure(state_or_404(t['thread_id']))
    except ValueError as exc: raise HTTPException(409,str(exc))
