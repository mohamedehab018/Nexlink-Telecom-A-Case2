"""Durable, shared persistence for state graphs (HITL is intentionally separate from failures).

Uses shared/failure_tickets for failure handling.
HITL remains as Person 1 implemented it (Person 3's responsibility).
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional
from shared.failure_tickets.service import FailureTicketService
from shared.failure_tickets.models import FailureType
from shared.hitl.contract import HumanDecision
from shared.hitl.store import SqliteHITLStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OutageRepository:
    def __init__(self, path: str):
        self.path = path
        self.migrate()
        self.failure_svc = FailureTicketService(path)
        self.hitl_store = SqliteHITLStore(path)

    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def migrate(self):
        """Create outage-specific tables."""
        with self.conn() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS outage_incidents (
                    incident_id TEXT PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    symptoms_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outage_runs (
                    thread_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    current_node TEXT NOT NULL,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outage_hypotheses (
                    id INTEGER PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    selected INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS outage_tool_audit (
                    id INTEGER PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS failure_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_json TEXT NOT NULL,
                    checkpoint_id INTEGER,
                    resolution_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outage_ticket_threads (
                    support_ticket_id INTEGER PRIMARY KEY,
                    thread_id TEXT NOT NULL
                );
            ''')

    def save_run(self, state: dict):
        now = _now()
        with self.conn() as c:
            c.execute(
                'INSERT INTO outage_incidents VALUES(?,?,?,?,?,?) ON CONFLICT(incident_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at',
                (state['incident_id'], state['account_id'], json.dumps(state['symptoms']),
                 state['current_state'], now, now)
            )
            c.execute(
                'INSERT INTO outage_runs VALUES(?,?,?,?,?,?) ON CONFLICT(thread_id) DO UPDATE SET current_node=excluded.current_node,status=excluded.status,state_json=excluded.state_json,updated_at=excluded.updated_at',
                (state['thread_id'], state['incident_id'], state['current_state'],
                 state['current_state'], json.dumps(state, default=str), now)
            )
            c.execute('DELETE FROM outage_hypotheses WHERE thread_id=?', (state['thread_id'],))
            for hypothesis in state.get('hypotheses', []):
                c.execute(
                    'INSERT INTO outage_hypotheses(thread_id,hypothesis,confidence,metadata_json,selected) VALUES(?,?,?,?,?)',
                    (state['thread_id'], hypothesis['hypothesis'], hypothesis['confidence'],
                     json.dumps(hypothesis, default=str), int(hypothesis.get('status') == 'selected'))
                )

    def state(self, thread_id: str) -> dict | None:
        with self.conn() as c:
            r = c.execute('SELECT state_json FROM outage_runs WHERE thread_id=?', (thread_id,)).fetchone()
            return json.loads(r[0]) if r else None

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
        with self.conn() as c:
            c.execute(
                'INSERT INTO outage_tool_audit(thread_id,tool_name,arguments_json,result_json,created_at) VALUES(?,?,?,?,?)',
                (thread_id, name, json.dumps(args), json.dumps(result, default=str), _now())
            )

    def tool_history(self, thread_id):
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                'SELECT * FROM outage_tool_audit WHERE thread_id=? ORDER BY id',
                (thread_id,)
            )]

    def hypotheses(self, thread_id):
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                'SELECT * FROM outage_hypotheses WHERE thread_id=? ORDER BY confidence DESC',
                (thread_id,)
            )]

    # --- HITL operations (delegated to the shared unified hitl_tasks store) ---

    def create_hitl(self, task_id, thread_id, action):
        self.hitl_store.create_request(
            run_id=thread_id, payload=action, thread_id=thread_id,
            graph_type='outage', task_id=task_id,
        )

    def decide_hitl(self, task_id, decision):
        """Commit one admin decision exactly once."""
        self.hitl_store.commit_decision(task_id, HumanDecision(
            status=decision['status'],
            actor_id=decision['actor_id'],
            notes=decision.get('notes', ''),
            modified_payload=decision.get('modification'),
        ))

    def hitl(self, task_id):
        return self.hitl_store.task(task_id)

    def hitls(self):
        return self.hitl_store.tasks(graph_type='outage')

    # --- Failure ticket operations (using shared/failure_tickets) ---

    def failure(self, ticket_id, thread_id, error, checkpoint_id) -> int:
        """Record a graph failure: queue entry + thread pointer.

        Writes the human-facing SUPPORT_TICKETS entry (via the shared
        service), the graph-side ``failure_tickets`` pointer row so the run
        can find its way home, and the support-id <-> thread mapping the
        resolve endpoint needs. Returns the real support ticket id — the
        caller must store it, not a freshly invented one.
        """
        account_id = error.get('account_id', 0) if isinstance(error, dict) else 0

        decision = self.failure_svc.handle_failure(
            run_id=0,
            thread_id=0,
            account_id=account_id,
            failure_type=FailureType.SYSTEM,
            failure_step=error.get('node', 'unknown') if isinstance(error, dict) else 'unknown',
            failure_reason=error.get('message', 'Unknown error') if isinstance(error, dict) else str(error),
            state_data=error if isinstance(error, dict) else {"error": str(error)}
        )

        now = _now()
        with self.conn() as c:
            c.execute(
                '''INSERT INTO failure_tickets(ticket_id,thread_id,status,error_json,checkpoint_id,resolution_json,created_at,updated_at)
                   VALUES(?,?,?,?,NULL,NULL,?,?)
                   ON CONFLICT(ticket_id) DO UPDATE SET status='open',
                     error_json=excluded.error_json, checkpoint_id=excluded.checkpoint_id,
                     updated_at=excluded.updated_at''',
                (str(ticket_id), str(thread_id),
                 json.dumps(error, default=str), checkpoint_id, now, now)
            )
            c.execute(
                "INSERT OR REPLACE INTO outage_ticket_threads(support_ticket_id,thread_id) VALUES(?,?)",
                (decision.ticket_id, str(thread_id))
            )
        return decision.ticket_id

    def resolve_ticket(self, ticket_id, resolution):
        """Resolve failure ticket using shared module."""
        try:
            int_ticket_id = int(str(ticket_id).replace('failure-', ''))
        except (ValueError, AttributeError):
            int_ticket_id = 0
        
        self.failure_svc.resolve_ticket(int_ticket_id, json.dumps(resolution))

    def investigate_ticket(self, ticket_id, investigation):
        """Record investigation: move the ticket to 'ongoing', not closed."""
        from shared.failure_tickets.models import TicketStatus, TicketUpdate
        try:
            int_ticket_id = int(str(ticket_id).replace('failure-', ''))
        except (ValueError, AttributeError):
            int_ticket_id = 0

        current = self.failure_svc.tickets.get(int_ticket_id)
        if current is None:
            return
        note = f"Investigating: {json.dumps(investigation)}"
        self.failure_svc.tickets.update(int_ticket_id, TicketUpdate(
            status=TicketStatus.ONGOING,
            description=f"{current.description}\n{note}",
        ))

    def tickets(self):
        """List unresolved failure tickets (open + investigating)."""
        from shared.failure_tickets.models import TicketStatus
        tickets = self.failure_svc.tickets.list_all(TicketStatus.OPEN)
        tickets += self.failure_svc.tickets.list_all(TicketStatus.ONGOING)
        return [t.model_dump() for t in tickets]

    def ticket(self, ticket_id):
        """Get failure ticket using shared module."""
        try:
            int_ticket_id = int(str(ticket_id).replace('failure-', ''))
        except (ValueError, AttributeError):
            return None

        ticket = self.failure_svc.get_ticket_details(int_ticket_id)
        if not ticket:
            return None
        return ticket.model_dump()

    def ticket_thread(self, ticket_id) -> Any:
        """Thread linked to a ticket. Accepts either id form:
        the graph-side 'failure-<uuid>' or the queue's integer id."""
        tid = str(ticket_id)
        with self.conn() as c:
            if tid.startswith('failure-'):
                row = c.execute(
                    "SELECT thread_id FROM failure_tickets WHERE ticket_id = ?",
                    (tid,),
                ).fetchone()
                return row["thread_id"] if row else None
            try:
                int_id = int(tid)
            except ValueError:
                return None
            row = c.execute(
                "SELECT thread_id FROM outage_ticket_threads WHERE support_ticket_id = ?",
                (int_id,),
            ).fetchone()
            return row["thread_id"] if row else None

    def _support_ticket_id(self, ticket_id) -> Optional[int]:
        """Resolve either id form to the SUPPORT_TICKETS integer id."""
        tid = str(ticket_id)
        try:
            return int(tid)
        except ValueError:
            pass
        thread = self.ticket_thread(tid)
        if thread is None:
            return None
        with self.conn() as c:
            row = c.execute(
                "SELECT support_ticket_id FROM outage_ticket_threads WHERE thread_id = ?",
                (str(thread),),
            ).fetchone()
            return row[0] if row else None

    def ticket_resolved(self, ticket_id) -> bool:
        """True when the queue ticket linked to this graph failure is closed.

        SUPPORT_TICKETS uses 'closed' (via the shared service); 'resolved'
        is accepted as an alias so either wording works.
        """
        support_id = self._support_ticket_id(ticket_id)
        if support_id is None:
            return False
        t = self.ticket(str(support_id))
        if not t:
            return False
        status = str(t.get("status")).lower().split(".")[-1]
        return status in {"closed", "resolved"}
