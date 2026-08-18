"""Failure handling system for Order-to-Activation Graph.

Manages failures, creates tickets, and handles retries.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any
from .states import GraphState, ActivationData


class FailureManager:
    """Manages failures and creates support tickets."""

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create failure log tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS failure_logs (
                    failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    failure_type TEXT NOT NULL,
                    failure_step TEXT NOT NULL,
                    failure_reason TEXT NOT NULL,
                    state_data TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id),
                    FOREIGN KEY (thread_id) REFERENCES threads(thread_id),
                    FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
                )
            """)
            conn.commit()

    def log_failure(
        self,
        run_id: int,
        thread_id: int,
        account_id: int,
        failure_type: str,
        failure_step: str,
        failure_reason: str,
        state_data: Optional[Dict[str, Any]] = None
    ) -> int:
        """Log a failure.
        
        Args:
            run_id: Current run ID
            thread_id: Current thread ID
            account_id: Account that failed
            failure_type: Type of failure (equipment, network, system, etc.)
            failure_step: Step where failure occurred
            failure_reason: Why it failed
            state_data: State data at time of failure
            
        Returns:
            Failure ID
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO failure_logs 
                   (run_id, thread_id, account_id, failure_type, failure_step, 
                    failure_reason, state_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, thread_id, account_id, failure_type, failure_step,
                 failure_reason, json.dumps(state_data) if state_data else None)
            )
            failure_id = cursor.lastrowid
            conn.commit()
            return failure_id

    def create_failure_ticket(
        self,
        account_id: int,
        failure_type: str,
        failure_reason: str,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a support ticket for a failure.
        
        Args:
            account_id: Account that failed
            failure_type: Type of failure
            failure_reason: Why it failed
            description: Additional details
            
        Returns:
            Ticket creation result
        """
        ticket_description = f"Activation Failure: {failure_type}\nReason: {failure_reason}"
        if description:
            ticket_description += f"\nDetails: {description}"
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO SUPPORT_TICKETS 
                   (account_id, ticket_type, status, description)
                   VALUES (?, 'technical', 'open', ?)""",
                (account_id, ticket_description)
            )
            ticket_id = cursor.lastrowid
            conn.commit()
            
            return {
                "success": True,
                "ticket_id": ticket_id,
                "account_id": account_id,
                "ticket_type": "technical",
                "status": "open",
                "message": f"Failure ticket #{ticket_id} created"
            }

    def should_retry(self, retry_count: int, max_retries: int = 3) -> bool:
        """Determine if we should retry the failed operation.
        
        Args:
            retry_count: Number of retries attempted
            max_retries: Maximum allowed retries
            
        Returns:
            True if should retry
        """
        return retry_count < max_retries

    def get_failure_history(self, account_id: int) -> list[Dict[str, Any]]:
        """Get failure history for an account.
        
        Args:
            account_id: Account to get history for
            
        Returns:
            List of failures
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM failure_logs 
                   WHERE account_id = ?
                   ORDER BY created_at DESC""",
                (account_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_run_failures(self, run_id: int) -> list[Dict[str, Any]]:
        """Get all failures for a specific run.
        
        Args:
            run_id: Run to get failures for
            
        Returns:
            List of failures
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM failure_logs 
                   WHERE run_id = ?
                   ORDER BY created_at""",
                (run_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def analyze_failure_pattern(self, account_id: int) -> Dict[str, Any]:
        """Analyze failure patterns for an account.
        
        Args:
            account_id: Account to analyze
            
        Returns:
            Failure analysis
        """
        failures = self.get_failure_history(account_id)
        
        if not failures:
            return {
                "account_id": account_id,
                "total_failures": 0,
                "patterns": [],
                "recommendation": "No failures recorded"
            }
        
        # Count failure types
        type_counts = {}
        step_counts = {}
        for f in failures:
            ft = f['failure_type']
            fs = f['failure_step']
            type_counts[ft] = type_counts.get(ft, 0) + 1
            step_counts[fs] = step_counts.get(fs, 0) + 1
        
        # Find most common failure
        most_common_type = max(type_counts.items(), key=lambda x: x[1])
        most_common_step = max(step_counts.items(), key=lambda x: x[1])
        
        # Generate recommendation
        if most_common_type[0] == "equipment":
            recommendation = "Consider checking equipment compatibility or assigning different model"
        elif most_common_type[0] == "network":
            recommendation = "Network issues detected. Consider dispatching technician"
        elif most_common_type[0] == "system":
            recommendation = "System error. Contact technical support"
        else:
            recommendation = "Review failure logs for specific issues"
        
        return {
            "account_id": account_id,
            "total_failures": len(failures),
            "failure_types": type_counts,
            "failure_steps": step_counts,
            "most_common_type": most_common_type[0],
            "most_common_step": most_common_step[0],
            "recommendation": recommendation
        }
