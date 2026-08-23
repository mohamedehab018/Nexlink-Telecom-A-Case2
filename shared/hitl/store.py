"""Unified HITL persistence shared by all graphs (outage, order_activation, ...).

Resolves the historical ``hitl_tasks`` schema collision:
  - graphs/outage used ``task_id TEXT PRIMARY KEY`` with action/decision JSON blobs
  - graphs/order_activation used ``task_id INTEGER PRIMARY KEY AUTOINCREMENT`` with columns

Unified contract: one table, TEXT primary key (outage passes its own
``hitl-<hex>`` ids; activation uses monotonically increasing numeric ids stored
as text), a ``graph_type`` discriminator, and JSON payloads for graph-specific
data. Legacy tables are detected via PRAGMA and migrated in place, preserving rows.

Decision commit is exactly-once: an atomic conditional UPDATE that only matches
rows still ``pending``, mirroring OutageRepository.decide_hitl.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from .contract import DECISION_STATUSES, HumanDecision

PENDING = 'pending'

UNIFIED_COLUMNS = (
    'task_id', 'graph_type', 'thread_id', 'run_id', 'account_id', 'task_type',
    'status', 'action_json', 'decision_json', 'created_at', 'updated_at',
)

HITL_TASKS_DDL = '''
    CREATE TABLE IF NOT EXISTS hitl_tasks (
        task_id TEXT PRIMARY KEY,
        graph_type TEXT NOT NULL,
        thread_id TEXT,
        run_id TEXT,
        account_id INTEGER,
        task_type TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending', 'approved', 'rejected', 'modified')),
        action_json TEXT NOT NULL,
        decision_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
'''


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(conn: sqlite3.Connection, table: str = 'hitl_tasks') -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info({table})')]


def _map_legacy_outage_row(row: dict) -> tuple:
    """(task_id, thread_id, status, action_json, decision_json, created_at, updated_at) shape."""
    return (
        str(row['task_id']), row['thread_id'], row['status'],
        row['action_json'], row['decision_json'],
        row.get('created_at') or _now(), row.get('updated_at') or _now(),
    )


def _map_legacy_activation_row(row: dict) -> tuple:
    """INTEGER-PK activation rows keep their numeric id as text; payload becomes JSON."""
    status = row['status'] or PENDING
    if status == PENDING:
        decision_json = None
    else:
        decision_json = json.dumps({
            'status': status,
            'actor_id': row.get('admin_id') or 'unknown',
            'notes': row.get('admin_notes') or '',
            'modification': None,
        })
    action = {'description': row.get('description') or ''}
    return (
        str(row['task_id']), 'order_activation', str(row['run_id']) if row.get('run_id') is not None else None,
        str(row['thread_id']) if row.get('thread_id') is not None else None,
        row.get('account_id'), row.get('task_type'), status,
        json.dumps(action), decision_json,
        row.get('created_at') or _now(), row.get('resolved_at') or row.get('updated_at') or _now(),
    )


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    old_cols = set(_columns(conn))
    if 'action_json' in old_cols:  # outage-style legacy table
        mapper, select = _map_legacy_outage_row, \
            'SELECT task_id, thread_id, status, action_json, decision_json, created_at, updated_at FROM hitl_tasks_legacy'
        insert_sql = ('INSERT INTO hitl_tasks(task_id,graph_type,thread_id,status,action_json,decision_json,created_at,updated_at) '
                      "VALUES(?,'outage',?,?,?,?,?,?)")
    elif 'admin_id' in old_cols:  # order_activation-style legacy table
        mapper, select = _map_legacy_activation_row, \
            'SELECT * FROM hitl_tasks_legacy'
        insert_sql = ('INSERT INTO hitl_tasks'
                      '(task_id,graph_type,run_id,thread_id,account_id,task_type,status,action_json,decision_json,created_at,updated_at) '
                      'VALUES(?,?,?,?,?,?,?,?,?,?,?)')
    else:
        raise ValueError(f'unrecognised legacy hitl_tasks schema: {sorted(old_cols)}')

    with conn:
        conn.execute('ALTER TABLE hitl_tasks RENAME TO hitl_tasks_legacy')
        conn.executescript(HITL_TASKS_DDL)
        for row in conn.execute(select).fetchall():
            conn.execute(insert_sql, mapper(dict(row)))
        conn.execute('DROP TABLE hitl_tasks_legacy')


def ensure_hitl_schema(conn_or_path: sqlite3.Connection | str) -> None:
    """Create or migrate the shared hitl_tasks table to the unified schema."""
    owns = isinstance(conn_or_path, str)
    if owns:
        conn = sqlite3.connect(conn_or_path)
        conn.row_factory = sqlite3.Row
    else:
        conn = conn_or_path
    try:
        cols = _columns(conn)
        if not cols:
            with conn:
                conn.executescript(HITL_TASKS_DDL)
        elif cols != list(UNIFIED_COLUMNS):
            _migrate_legacy(conn)
    finally:
        if owns:
            conn.close()


class SqliteHITLStore:
    """Concrete HITLAdapter: durable requests, exact-once decisions.

    Implements the shared.hitl.contract.HITLAdapter Protocol.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        ensure_hitl_schema(db_path)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    # --- Protocol surface -------------------------------------------------

    def create_request(
        self,
        run_id: str,
        payload: dict,
        *,
        thread_id: str | None = None,
        graph_type: str = 'outage',
        account_id: int | None = None,
        task_type: str | None = None,
        task_id: str | None = None,
        id_mode: str = 'uuid',
    ) -> str:
        """Persist a pending human-approval request and return its id."""
        if not isinstance(payload, dict) or not payload:
            raise ValueError('payload must be a non-empty dict')
        now = _now()
        with self._conn() as c:
            if task_id is not None:
                task_id = str(task_id)
            elif id_mode == 'numeric':
                nxt = c.execute(
                    "SELECT COALESCE(MAX(CAST(task_id AS INTEGER)),0)+1 AS next "
                    "FROM hitl_tasks WHERE task_id NOT GLOB '*[^0-9]*'"
                ).fetchone()['next']
                task_id = str(nxt)
            else:
                task_id = f'hitl-{uuid4().hex}'
            try:
                c.execute(
                    'INSERT INTO hitl_tasks'
                    '(task_id,graph_type,thread_id,run_id,account_id,task_type,status,action_json,decision_json,created_at,updated_at) '
                    "VALUES(?,?,?,?,?,?, 'pending', ?, NULL, ?, ?)",
                    (task_id, graph_type, thread_id, run_id, account_id, task_type, json.dumps(payload, default=str), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f'HITL request id already exists: {task_id}') from exc
        return task_id

    def get_decision(self, request_id: str) -> HumanDecision | None:
        """The committed decision, or None while the task is still pending/unknown."""
        row = self.task(request_id)
        if not row or row['status'] == PENDING:
            return None
        d = json.loads(row['decision_json'])
        return HumanDecision(
            status=d['status'],
            actor_id=d['actor_id'],
            notes=d.get('notes', ''),
            modified_payload=d.get('modification'),
        )

    # --- Exact-once commit --------------------------------------------------

    def commit_decision(self, request_id: str, decision: HumanDecision) -> None:
        """Commit one admin decision exactly once; later attempts raise.

        Follows the OutageRepository pattern: an atomic conditional UPDATE that
        only matches pending rows, verified by rowcount inside the transaction.
        """
        self._validate(decision)
        stored = {
            'status': decision.status,
            'actor_id': decision.actor_id,
            'notes': decision.notes,
            'modification': decision.modified_payload,
        }
        with self._conn() as c:
            result = c.execute(
                f'UPDATE hitl_tasks SET status=?,decision_json=?,updated_at=? '
                f"WHERE task_id=? AND status='{PENDING}'",
                (decision.status, json.dumps(stored), _now(), str(request_id)),
            )
            if result.rowcount != 1:
                raise ValueError('HITL task is no longer pending')

    @staticmethod
    def _validate(decision: HumanDecision) -> None:
        if decision.status not in DECISION_STATUSES:
            raise ValueError(f'decision status must be one of {DECISION_STATUSES}')
        if not decision.actor_id:
            raise ValueError('actor_id is required')
        if decision.status == 'modified':
            if not isinstance(decision.modified_payload, dict) or not decision.modified_payload:
                raise ValueError('a modified decision requires a non-empty modified_payload dict')
        elif decision.modified_payload is not None:
            raise ValueError('modified_payload is only valid for modified decisions')

    # --- Read helpers -------------------------------------------------------

    def task(self, request_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute('SELECT * FROM hitl_tasks WHERE task_id=?', (str(request_id),)).fetchone()
            return dict(r) if r else None

    def tasks(
        self,
        *,
        status: str | None = None,
        graph_type: str | None = None,
        account_id: int | None = None,
    ) -> list[dict]:
        query = 'SELECT * FROM hitl_tasks'
        filters, params = [], []
        if status:
            filters.append('status=?'); params.append(status)
        if graph_type:
            filters.append('graph_type=?'); params.append(graph_type)
        if account_id is not None:
            filters.append('account_id=?'); params.append(account_id)
        if filters:
            query += ' WHERE ' + ' AND '.join(filters)
        query += ' ORDER BY updated_at DESC'
        with self._conn() as c:
            return [dict(r) for r in c.execute(query, params)]
