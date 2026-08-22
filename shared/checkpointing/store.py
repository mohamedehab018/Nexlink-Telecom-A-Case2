"""Atomic SQLite checkpoints shared by all Nexlink state graphs.

Uses the shared threads, runs, and checkpoints tables.
Payload is intentionally opaque JSON: graph-specific fields belong to the caller.
The ``completed_effects`` map provides an idempotency ledger across process restarts.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA_VERSION = 1


class CheckpointStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        """Create shared tables if they don't exist."""
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    graph_type TEXT NOT NULL CHECK(graph_type IN ('outage', 'order_activation', 'sla_dispute')),
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'failed')),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id INTEGER NOT NULL,
                    graph_type TEXT NOT NULL CHECK(graph_type IN ('outage', 'order_activation', 'sla_dispute')),
                    state TEXT,
                    status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running', 'completed', 'failed', 'paused')),
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    FOREIGN KEY (thread_id) REFERENCES threads(thread_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    step_number INTEGER NOT NULL,
                    state_data TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _get_or_create_thread(self, run_id: str, graph_name: str, account_id: int = 0) -> int:
        """Get or create thread for this run_id."""
        conn = self._connect()
        try:
            # Check if thread exists by run_id mapping
            row = conn.execute(
                "SELECT thread_id FROM runs WHERE state LIKE ?",
                (f'%"thread_id": "{run_id}"%',)
            ).fetchone()
            
            if row:
                return row['thread_id']
            
            # Create new thread
            cursor = conn.execute(
                "INSERT INTO threads (account_id, graph_type) VALUES (?, ?)",
                (account_id, graph_name)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def _get_or_create_run(self, thread_id: int, run_id: str, graph_name: str) -> int:
        """Get or create run for this thread."""
        conn = self._connect()
        try:
            # Check if run exists
            row = conn.execute(
                "SELECT run_id FROM runs WHERE thread_id = ? AND state LIKE ?",
                (thread_id, f'%"thread_id": "{run_id}"%',)
            ).fetchone()
            
            if row:
                return row['run_id']
            
            # Create new run
            cursor = conn.execute(
                "INSERT INTO runs (thread_id, graph_type, state) VALUES (?, ?, ?)",
                (thread_id, graph_name, json.dumps({"thread_id": run_id}))
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def save(self, run_id: str, graph_name: str, state: Mapping[str, Any], version: int = SCHEMA_VERSION) -> int:
        """Save checkpoint to shared tables."""
        payload = json.dumps(dict(state), sort_keys=True, default=str)
        
        # Extract account_id from state if available
        account_id = state.get('account_id', 0)
        
        conn = self._connect()
        try:
            # Get or create thread
            thread_row = conn.execute(
                "SELECT thread_id FROM runs WHERE state LIKE ?",
                (f'%"thread_id": "{run_id}"%',)
            ).fetchone()
            
            if thread_row:
                thread_id = thread_row['thread_id']
            else:
                cursor = conn.execute(
                    "INSERT INTO threads (account_id, graph_type) VALUES (?, ?)",
                    (account_id, graph_name)
                )
                thread_id = cursor.lastrowid
            
            # Get or create run
            run_row = conn.execute(
                "SELECT run_id FROM runs WHERE thread_id = ? AND state LIKE ?",
                (thread_id, f'%"thread_id": "{run_id}"%',)
            ).fetchone()
            
            if run_row:
                db_run_id = run_row['run_id']
            else:
                cursor = conn.execute(
                    "INSERT INTO runs (thread_id, graph_type, state) VALUES (?, ?, ?)",
                    (thread_id, graph_name, payload)
                )
                db_run_id = cursor.lastrowid
            
            # Count existing checkpoints for step number
            step_row = conn.execute(
                "SELECT COUNT(*) as count FROM checkpoints WHERE run_id = ?",
                (db_run_id,)
            ).fetchone()
            step_number = step_row['count']
            
            # Save checkpoint
            cursor = conn.execute(
                "INSERT INTO checkpoints (run_id, step_number, state_data) VALUES (?, ?, ?)",
                (db_run_id, step_number, payload)
            )
            
            # Update run state
            conn.execute(
                "UPDATE runs SET state = ?, status = 'running' WHERE run_id = ?",
                (payload, db_run_id)
            )
            
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def load_latest(self, run_id: str, compatible_versions: set[int] | None = None) -> dict[str, Any] | None:
        """Load latest checkpoint from shared tables."""
        conn = self._connect()
        try:
            # Find the run
            row = conn.execute(
                "SELECT run_id FROM runs WHERE state LIKE ?",
                (f'%"thread_id": "{run_id}"%',)
            ).fetchone()
            
            if not row:
                return None
            
            db_run_id = row['run_id']
            
            # Get latest checkpoint
            checkpoint = conn.execute(
                "SELECT * FROM checkpoints WHERE run_id = ? ORDER BY step_number DESC LIMIT 1",
                (db_run_id,)
            ).fetchone()
            
            if not checkpoint:
                return None
            
            try:
                state = json.loads(checkpoint['state_data'])
                if not isinstance(state, dict):
                    raise ValueError('state is not an object')
                state['checkpoint_id'] = checkpoint['checkpoint_id']
                return state
            except (ValueError, TypeError, json.JSONDecodeError):
                return None
        finally:
            conn.close()

    def history(self, run_id: str) -> list[dict[str, Any]]:
        """Inspectable, durable checkpoint metadata for platform/admin recovery."""
        conn = self._connect()
        try:
            # Find the run
            row = conn.execute(
                "SELECT run_id FROM runs WHERE state LIKE ?",
                (f'%"thread_id": "{run_id}"%',)
            ).fetchone()
            
            if not row:
                return []
            
            db_run_id = row['run_id']
            
            rows = conn.execute(
                "SELECT checkpoint_id, run_id, step_number, state_data, created_at FROM checkpoints WHERE run_id = ? ORDER BY step_number DESC",
                (db_run_id,)
            ).fetchall()
            
            return [
                {
                    "checkpoint_id": r['checkpoint_id'],
                    "step_number": r['step_number'],
                    "state": json.loads(r['state_data']),
                    "created_at": r['created_at']
                }
                for r in rows
            ]
        finally:
            conn.close()


def save_checkpoint(store: CheckpointStore, run_id: str, graph_name: str, state: Mapping[str, Any]) -> int:
    return store.save(run_id, graph_name, state)


def load_checkpoint(store: CheckpointStore, run_id: str) -> dict[str, Any] | None:
    return store.load_latest(run_id)


def resume_run(store: CheckpointStore, run_id: str, runner: Callable[[dict[str, Any]], Any]) -> Any:
    state = load_checkpoint(store, run_id)
    if state is None:
        raise LookupError(f"No valid checkpoint for run {run_id}")
    return runner(state)
