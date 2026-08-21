"""Durable, shared persistence for state graphs (HITL is intentionally separate from failures)."""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from typing import Any

def _now() -> str: return datetime.now(timezone.utc).isoformat()

class OutageRepository:
    def __init__(self, path: str):
        self.path = path; self.migrate()
    def conn(self):
        c=sqlite3.connect(self.path); c.row_factory=sqlite3.Row; return c
    def migrate(self):
        with self.conn() as c: c.executescript('''
CREATE TABLE IF NOT EXISTS outage_incidents (incident_id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, symptoms_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outage_runs (thread_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, current_node TEXT NOT NULL, status TEXT NOT NULL, state_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outage_hypotheses (id INTEGER PRIMARY KEY, thread_id TEXT NOT NULL, hypothesis TEXT NOT NULL, confidence REAL NOT NULL, metadata_json TEXT NOT NULL, selected INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS outage_tool_audit (id INTEGER PRIMARY KEY, thread_id TEXT NOT NULL, tool_name TEXT NOT NULL, arguments_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hitl_tasks (task_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, status TEXT NOT NULL, action_json TEXT NOT NULL, decision_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS failure_tickets (ticket_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, status TEXT NOT NULL, error_json TEXT NOT NULL, checkpoint_id INTEGER, resolution_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
''')
    def save_run(self, state: dict):
        now=_now()
        with self.conn() as c:
            c.execute('INSERT INTO outage_incidents VALUES(?,?,?,?,?,?) ON CONFLICT(incident_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at',(state['incident_id'],state['account_id'],json.dumps(state['symptoms']),state['current_state'],now,now))
            c.execute('INSERT INTO outage_runs VALUES(?,?,?,?,?,?) ON CONFLICT(thread_id) DO UPDATE SET current_node=excluded.current_node,status=excluded.status,state_json=excluded.state_json,updated_at=excluded.updated_at',(state['thread_id'],state['incident_id'],state['current_state'],state['current_state'],json.dumps(state,default=str),now))
            c.execute('DELETE FROM outage_hypotheses WHERE thread_id=?',(state['thread_id'],))
            for hypothesis in state.get('hypotheses',[]):
                c.execute('INSERT INTO outage_hypotheses(thread_id,hypothesis,confidence,metadata_json,selected) VALUES(?,?,?,?,?)',(state['thread_id'],hypothesis['hypothesis'],hypothesis['confidence'],json.dumps(hypothesis,default=str),int(hypothesis.get('status')=='selected')))
    def state(self, thread_id: str) -> dict | None:
        with self.conn() as c:
            r=c.execute('SELECT state_json FROM outage_runs WHERE thread_id=?',(thread_id,)).fetchone(); return json.loads(r[0]) if r else None
    def list_incidents(self):
        """List rows must expose the run identifier used by the details endpoint."""
        with self.conn() as c:
            return [dict(r) for r in c.execute('''
                SELECT i.*, r.thread_id, r.current_node, r.status AS run_status
                FROM outage_incidents i
                JOIN outage_runs r ON r.incident_id = i.incident_id
                WHERE r.updated_at = (SELECT MAX(r2.updated_at) FROM outage_runs r2 WHERE r2.incident_id=i.incident_id)
                ORDER BY i.updated_at DESC
            ''')]
    def audit(self, thread_id, name, args, result):
        with self.conn() as c: c.execute('INSERT INTO outage_tool_audit(thread_id,tool_name,arguments_json,result_json,created_at) VALUES(?,?,?,?,?)',(thread_id,name,json.dumps(args),json.dumps(result,default=str),_now()))
    def tool_history(self, thread_id):
        with self.conn() as c: return [dict(r) for r in c.execute('SELECT * FROM outage_tool_audit WHERE thread_id=? ORDER BY id',(thread_id,))]
    def hypotheses(self,thread_id):
        with self.conn() as c:return [dict(r) for r in c.execute('SELECT * FROM outage_hypotheses WHERE thread_id=? ORDER BY confidence DESC',(thread_id,))]
    def create_hitl(self, task_id, thread_id, action):
        now=_now()
        with self.conn() as c: c.execute('INSERT INTO hitl_tasks VALUES(?,?,?,?,?,?,?)',(task_id,thread_id,'pending',json.dumps(action),None,now,now))
    def decide_hitl(self, task_id, decision):
        """Commit one admin decision exactly once.

        A task is an independently persisted work item, rather than a UI-only
        representation of an interrupt.  The conditional update prevents a
        stale browser tab from changing a decision after the graph resumed.
        """
        with self.conn() as c:
            result = c.execute(
                'UPDATE hitl_tasks SET status=?,decision_json=?,updated_at=? '
                'WHERE task_id=? AND status="pending"',
                (decision['status'], json.dumps(decision), _now(), task_id),
            )
            if result.rowcount != 1:
                raise ValueError('HITL task is no longer pending')
    def hitl(self, task_id):
        with self.conn() as c:
            r=c.execute('SELECT * FROM hitl_tasks WHERE task_id=?',(task_id,)).fetchone(); return dict(r) if r else None
    def hitls(self):
        with self.conn() as c:return [dict(r) for r in c.execute('SELECT * FROM hitl_tasks ORDER BY updated_at DESC')]
    def failure(self, ticket_id, thread_id, error, checkpoint_id):
        now=_now()
        with self.conn() as c:c.execute('INSERT INTO failure_tickets VALUES(?,?,?,?,?,?,?,?)',(ticket_id,thread_id,'open',json.dumps(error),checkpoint_id,None,now,now))
    def resolve_ticket(self,ticket_id, resolution):
        with self.conn() as c:
            result=c.execute('UPDATE failure_tickets SET status="resolved",resolution_json=?,updated_at=? WHERE ticket_id=? AND status IN ("open","investigating")',(json.dumps(resolution),_now(),ticket_id))
            if result.rowcount != 1: raise ValueError('failure ticket is not resolvable')
    def investigate_ticket(self, ticket_id, investigation):
        """Record that an unexpected failure is being investigated; no resume."""
        with self.conn() as c:
            result=c.execute('UPDATE failure_tickets SET status="investigating",resolution_json=?,updated_at=? WHERE ticket_id=? AND status="open"',(json.dumps(investigation),_now(),ticket_id))
            if result.rowcount != 1: raise ValueError('failure ticket is not open')
    def tickets(self):
        with self.conn() as c:return [dict(r) for r in c.execute('SELECT * FROM failure_tickets ORDER BY updated_at DESC')]
    def ticket(self,ticket_id):
        with self.conn() as c:
            r=c.execute('SELECT * FROM failure_tickets WHERE ticket_id=?',(ticket_id,)).fetchone();return dict(r) if r else None
