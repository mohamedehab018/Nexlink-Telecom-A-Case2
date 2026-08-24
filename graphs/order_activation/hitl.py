"""Human-in-the-Loop (HITL) system for Order-to-Activation Graph.

Handles human approval requests and graph pause/resume.

Backed by the shared unified ``hitl_tasks`` store (shared/hitl/store.py) so the
activation graph and the outage graph no longer declare conflicting schemas for
the same table. Numeric task ids are preserved for API compatibility; modified
decisions are supported through the shared adapter even though this graph does
not use them yet.
"""
from __future__ import annotations
import json
from typing import Any, Dict, Optional

from shared.hitl.contract import HumanDecision
from shared.hitl.store import PENDING, SqliteHITLStore


class HITLManager:
    """Manages human approval requests for the activation graph."""

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db_path = db_path
        self.store = SqliteHITLStore(db_path)

    def _compat_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Expose legacy column names (admin_id/admin_notes/resolved_at)."""
        decision = json.loads(row["decision_json"]) if row.get("decision_json") else {}
        return {
            "task_id": row["task_id"],
            "run_id": row.get("run_id"),
            "thread_id": row.get("thread_id"),
            "account_id": row.get("account_id"),
            "task_type": row.get("task_type"),
            "status": row["status"],
            "admin_id": decision.get("actor_id"),
            "admin_notes": decision.get("notes"),
            "created_at": row.get("created_at"),
            "resolved_at": row.get("updated_at") if row["status"] != PENDING else None,
            "action": json.loads(row["action_json"]) if row.get("action_json") else {},
            "decision": decision or None,
        }

    @staticmethod
    def _as_int(task_id) -> int:
        return int(str(task_id))

    def create_approval_request(
        self,
        run_id: int,
        thread_id: int,
        account_id: int,
        task_type: str,
        description: str,
        state_data: Optional[Dict[str, Any]] = None
    ) -> int:
        """Create a human approval request and return its numeric task id."""
        payload: Dict[str, Any] = {"description": description}
        if state_data is not None:
            payload["state_data"] = state_data
        task_id = self.store.create_request(
            run_id=str(run_id),
            payload=payload,
            thread_id=str(thread_id),
            graph_type="order_activation",
            account_id=account_id,
            task_type=task_type,
            id_mode="numeric",
        )
        return self._as_int(task_id)

    def get_pending_tasks(self, account_id: Optional[int] = None) -> list[Dict[str, Any]]:
        """Get pending HITL tasks, optionally filtered by account."""
        rows = self.store.tasks(status=PENDING, graph_type="order_activation", account_id=account_id)
        return [self._compat_view(r) for r in rows]

    def _decide(self, task_id: int, decision: HumanDecision):
        try:
            self.store.commit_decision(task_id, decision)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        return {
            "success": True,
            "task_id": self._as_int(task_id),
            "status": decision.status,
            "admin_id": decision.actor_id,
            "message": f"Task #{self._as_int(task_id)} {decision.status}",
        }

    def modify_task(
        self,
        task_id: int,
        admin_id: str,
        modification: Dict[str, Any],
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Modify and approve a task in one exact-once commit (available to activation)."""
        result = self._decide(task_id, HumanDecision(
            status="modified", actor_id=admin_id, notes=notes or "",
            modified_payload=modification,
        ))
        if result["success"]:
            result["modification"] = modification
        return result

    def approve_task(
        self,
        task_id: int,
        admin_id: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Approve a HITL task exactly once."""
        if not self.store.task(self._as_int(task_id)):
            return {"success": False, "error": "Task not found"}
        return self._decide(task_id, HumanDecision(
            status="approved", actor_id=admin_id, notes=notes or "",
        ))

    def reject_task(
        self,
        task_id: int,
        admin_id: str,
        reason: str
    ) -> Dict[str, Any]:
        """Reject a HITL task exactly once."""
        if not self.store.task(self._as_int(task_id)):
            return {"success": False, "error": "Task not found"}
        result = self._decide(task_id, HumanDecision(
            status="rejected", actor_id=admin_id, notes=reason,
        ))
        if result["success"]:
            result["reason"] = reason
        return result

    def check_approval_status(self, task_id: int) -> Dict[str, Any]:
        """Check if a task has been decided."""
        row = self.store.task(self._as_int(task_id))
        if not row:
            return {"exists": False}
        view = self._compat_view(row)
        return {
            "exists": True,
            "task_id": self._as_int(task_id),
            "status": view["status"],
            "admin_id": view["admin_id"],
            "admin_notes": view["admin_notes"],
            "resolved_at": view["resolved_at"],
        }

    def get_task_history(self, account_id: int) -> list[Dict[str, Any]]:
        """Get all HITL tasks for an account."""
        rows = self.store.tasks(graph_type="order_activation", account_id=account_id)
        return [self._compat_view(r) for r in rows]
