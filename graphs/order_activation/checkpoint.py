"""Checkpoint system for Order-to-Activation Graph.

Saves and restores graph state for crash recovery.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from typing import Optional
from .states import GraphState, ActivationData


class CheckpointManager:
    """Manages checkpoints for crash recovery."""

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create checkpoint tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
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

    def create_thread(self, account_id: int) -> int:
        """Create a new thread for this activation."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO threads (account_id, graph_type) VALUES (?, 'order_activation')",
                (account_id,)
            )
            conn.commit()
            return cursor.lastrowid

    def create_run(self, thread_id: int) -> int:
        """Create a new run for this thread."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO runs (thread_id, graph_type, state) VALUES (?, 'order_activation', ?)",
                (thread_id, GraphState.START.value)
            )
            conn.commit()
            return cursor.lastrowid

    def save_checkpoint(
        self,
        run_id: int,
        step_number: int,
        state: GraphState,
        data: ActivationData
    ) -> int:
        """Save a checkpoint with current state and data."""
        state_data = json.dumps({
            "state": state.value,
            "data": data.to_dict(),
            "timestamp": datetime.utcnow().isoformat()
        })
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO checkpoints (run_id, step_number, state_data) VALUES (?, ?, ?)",
                (run_id, step_number, state_data)
            )
            conn.execute(
                "UPDATE runs SET state = ? WHERE run_id = ?",
                (state.value, run_id)
            )
            conn.commit()
            return cursor.lastrowid

    def load_checkpoint(self, run_id: int) -> Optional[tuple[GraphState, ActivationData]]:
        """Load the latest checkpoint for a run."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT state_data FROM checkpoints 
                   WHERE run_id = ? 
                   ORDER BY step_number DESC 
                   LIMIT 1""",
                (run_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            state_data = json.loads(row[0])
            state = GraphState(state_data["state"])
            data = ActivationData.from_dict(state_data["data"])
            return state, data

    def update_run_status(self, run_id: int, status: str) -> None:
        """Update run status (completed, failed, paused)."""
        with sqlite3.connect(self.db_path) as conn:
            if status in ("completed", "failed"):
                conn.execute(
                    "UPDATE runs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE run_id = ?",
                    (status, run_id)
                )
            else:
                conn.execute(
                    "UPDATE runs SET status = ? WHERE run_id = ?",
                    (status, run_id)
                )
            conn.commit()

    def update_thread_status(self, thread_id: int, status: str) -> None:
        """Update thread status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE threads SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
                (status, thread_id)
            )
            conn.commit()

    def get_thread_runs(self, thread_id: int) -> list[dict]:
        """Get all runs for a thread."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM runs WHERE thread_id = ? ORDER BY started_at",
                (thread_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_run_checkpoints(self, run_id: int) -> list[dict]:
        """Get all checkpoints for a run."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM checkpoints WHERE run_id = ? ORDER BY step_number",
                (run_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
