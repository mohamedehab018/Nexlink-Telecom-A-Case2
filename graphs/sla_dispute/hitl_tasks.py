"""Persistent administrative review tasks for SLA disputes."""
from dataclasses import dataclass
from typing import Optional

from mcp_server.db import get_connection


@dataclass
class HITLTask:
    task_id: int
    run_id: str
    customer_id: int
    task_type: str
    message: str
    status: str = "pending"
    decision: Optional[str] = None
    reviewer: Optional[str] = None


class HITLTaskManager:
    def _ensure_table(self) -> None:
        with get_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS sla_dispute_hitl_tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                customer_id INTEGER NOT NULL, task_type TEXT NOT NULL, message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', decision TEXT, reviewer TEXT
            )""")
            conn.commit()

    def create_task(self, run_id: str, customer_id: int, task_type: str, message: str) -> HITLTask:
        if not all(isinstance(x, str) and x.strip() for x in (run_id, task_type, message)) or customer_id is None:
            raise ValueError("run_id, customer_id, task_type and message are required.")
        self._ensure_table()
        with get_connection() as conn:
            cursor = conn.execute("INSERT INTO sla_dispute_hitl_tasks (run_id, customer_id, task_type, message) VALUES (?, ?, ?, ?)", (run_id.strip(), customer_id, task_type.strip(), message.strip()))
            conn.commit()
            task_id = cursor.lastrowid
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("Failed to create HITL task.")
        return task

    def get_task(self, task_id: int) -> Optional[HITLTask]:
        self._ensure_table()
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM sla_dispute_hitl_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return HITLTask(**dict(row)) if row else None

    def _resolve_task(self, task_id: int, decision: str, reviewer: str) -> HITLTask:
        if decision not in {"approve", "reject"} or not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("A valid decision and reviewer are required.")
        status = "approved" if decision == "approve" else "rejected"
        with get_connection() as conn:
            cursor = conn.execute("UPDATE sla_dispute_hitl_tasks SET status=?, decision=?, reviewer=? WHERE task_id=? AND status='pending'", (status, decision, reviewer.strip(), task_id))
            conn.commit()
        if cursor.rowcount != 1:
            raise ValueError(f"HITL task #{task_id} is missing or already resolved.")
        return self.get_task(task_id)  # type: ignore[return-value]

    def approve(self, task_id: int, reviewer: str = "admin") -> HITLTask:
        return self._resolve_task(task_id, "approve", reviewer)

    def reject(self, task_id: int, reviewer: str = "admin") -> HITLTask:
        return self._resolve_task(task_id, "reject", reviewer)

    def list_pending(self) -> list[HITLTask]:
        return self.list_tasks("pending")

    def list_tasks(self, status: Optional[str] = None) -> list[HITLTask]:
        self._ensure_table()
        query = "SELECT * FROM sla_dispute_hitl_tasks" + (" WHERE status = ?" if status else "") + " ORDER BY task_id DESC"
        with get_connection() as conn:
            rows = conn.execute(query, (status,) if status else ()).fetchall()
        return [HITLTask(**dict(row)) for row in rows]


hitl_task_manager = HITLTaskManager()
