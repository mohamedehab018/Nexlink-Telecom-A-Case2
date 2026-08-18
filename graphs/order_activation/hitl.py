"""Human-in-the-Loop (HITL) system for Order-to-Activation Graph.

Handles human approval requests and graph pause/resume.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any
from .states import GraphState, ActivationData


class HITLManager:
    """Manages human approval requests for the activation graph."""

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create HITL tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hitl_tasks (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    task_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
                    admin_id TEXT,
                    admin_notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id),
                    FOREIGN KEY (thread_id) REFERENCES threads(thread_id),
                    FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
                )
            """)
            conn.commit()

    def create_approval_request(
        self,
        run_id: int,
        thread_id: int,
        account_id: int,
        task_type: str,
        description: str,
        state_data: Optional[Dict[str, Any]] = None
    ) -> int:
        """Create a human approval request.
        
        Args:
            run_id: Current run ID
            thread_id: Current thread ID
            account_id: Account being activated
            task_type: Type of approval (equipment_cost, config_change, etc.)
            description: What needs approval
            state_data: State data to save for resumption
            
        Returns:
            Task ID for tracking
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO hitl_tasks 
                   (run_id, thread_id, account_id, task_type, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (run_id, thread_id, account_id, task_type, description)
            )
            task_id = cursor.lastrowid
            conn.commit()
            return task_id

    def get_pending_tasks(self, account_id: Optional[int] = None) -> list[Dict[str, Any]]:
        """Get pending HITL tasks, optionally filtered by account.
        
        Args:
            account_id: Optional account ID to filter by
            
        Returns:
            List of pending tasks
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if account_id:
                cursor = conn.execute(
                    """SELECT * FROM hitl_tasks 
                       WHERE status = 'pending' AND account_id = ?
                       ORDER BY created_at""",
                    (account_id,)
                )
            else:
                cursor = conn.execute(
                    """SELECT * FROM hitl_tasks 
                       WHERE status = 'pending'
                       ORDER BY created_at"""
                )
            return [dict(row) for row in cursor.fetchall()]

    def approve_task(
        self,
        task_id: int,
        admin_id: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Approve a HITL task.
        
        Args:
            task_id: Task to approve
            admin_id: Admin who approved
            notes: Optional notes
            
        Returns:
            Approval result
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            task = conn.execute(
                "SELECT * FROM hitl_tasks WHERE task_id = ?",
                (task_id,)
            ).fetchone()
            
            if not task:
                return {"success": False, "error": "Task not found"}
            
            if task['status'] != 'pending':
                return {"success": False, "error": f"Task already {task['status']}"}
            
            conn.execute(
                """UPDATE hitl_tasks 
                   SET status = 'approved', admin_id = ?, admin_notes = ?, 
                       resolved_at = CURRENT_TIMESTAMP
                   WHERE task_id = ?""",
                (admin_id, notes, task_id)
            )
            conn.commit()
            
            return {
                "success": True,
                "task_id": task_id,
                "status": "approved",
                "admin_id": admin_id,
                "message": f"Task #{task_id} approved"
            }

    def reject_task(
        self,
        task_id: int,
        admin_id: str,
        reason: str
    ) -> Dict[str, Any]:
        """Reject a HITL task.
        
        Args:
            task_id: Task to reject
            admin_id: Admin who rejected
            reason: Rejection reason
            
        Returns:
            Rejection result
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            task = conn.execute(
                "SELECT * FROM hitl_tasks WHERE task_id = ?",
                (task_id,)
            ).fetchone()
            
            if not task:
                return {"success": False, "error": "Task not found"}
            
            if task['status'] != 'pending':
                return {"success": False, "error": f"Task already {task['status']}"}
            
            conn.execute(
                """UPDATE hitl_tasks 
                   SET status = 'rejected', admin_id = ?, admin_notes = ?,
                       resolved_at = CURRENT_TIMESTAMP
                   WHERE task_id = ?""",
                (admin_id, reason, task_id)
            )
            conn.commit()
            
            return {
                "success": True,
                "task_id": task_id,
                "status": "rejected",
                "admin_id": admin_id,
                "reason": reason,
                "message": f"Task #{task_id} rejected"
            }

    def check_approval_status(self, task_id: int) -> Dict[str, Any]:
        """Check if a task has been approved.
        
        Args:
            task_id: Task to check
            
        Returns:
            Status information
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            task = conn.execute(
                "SELECT * FROM hitl_tasks WHERE task_id = ?",
                (task_id,)
            ).fetchone()
            
            if not task:
                return {"exists": False}
            
            return {
                "exists": True,
                "task_id": task_id,
                "status": task['status'],
                "admin_id": task['admin_id'],
                "admin_notes": task['admin_notes'],
                "resolved_at": task['resolved_at']
            }

    def get_task_history(self, account_id: int) -> list[Dict[str, Any]]:
        """Get all HITL tasks for an account.
        
        Args:
            account_id: Account to get history for
            
        Returns:
            List of tasks
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM hitl_tasks 
                   WHERE account_id = ?
                   ORDER BY created_at DESC""",
                (account_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
