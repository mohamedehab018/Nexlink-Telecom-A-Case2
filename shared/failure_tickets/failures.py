"""Failure logging operations."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from typing import Optional
from contextlib import contextmanager
from .models import (
    FailureLogCreate, FailureLogResponse,
    FailureType, FailureAnalysis
)


class FailureManager:
    """Manages failure logging operations."""

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create failure_logs table if it doesn't exist."""
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

    @contextmanager
    def _get_conn(self):
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def log(self, failure: FailureLogCreate) -> FailureLogResponse:
        """Log a failure.
        
        Args:
            failure: Failure data
            
        Returns:
            Created failure log
        """
        with self._get_conn() as conn:
            state_data = json.dumps(failure.state_data) if failure.state_data else None
            
            cursor = conn.execute(
                """INSERT INTO failure_logs 
                   (run_id, thread_id, account_id, failure_type, 
                    failure_step, failure_reason, state_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (failure.run_id, failure.thread_id, failure.account_id,
                 failure.failure_type.value, failure.failure_step,
                 failure.failure_reason, state_data)
            )
            failure_id = cursor.lastrowid
            conn.commit()
            
            return self.get(failure_id)

    def get(self, failure_id: int) -> Optional[FailureLogResponse]:
        """Get a failure log by ID.
        
        Args:
            failure_id: Failure ID
            
        Returns:
            Failure log or None
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM failure_logs WHERE failure_id = ?",
                (failure_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_response(row)

    def list_by_account(self, account_id: int) -> list[FailureLogResponse]:
        """List all failures for an account.
        
        Args:
            account_id: Account ID
            
        Returns:
            List of failure logs
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM failure_logs 
                   WHERE account_id = ?
                   ORDER BY created_at DESC""",
                (account_id,)
            ).fetchall()
            
            return [self._row_to_response(row) for row in rows]

    def list_by_run(self, run_id: int) -> list[FailureLogResponse]:
        """List all failures for a run.
        
        Args:
            run_id: Run ID
            
        Returns:
            List of failure logs
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM failure_logs 
                   WHERE run_id = ?
                   ORDER BY created_at""",
                (run_id,)
            ).fetchall()
            
            return [self._row_to_response(row) for row in rows]

    def analyze(self, account_id: int) -> FailureAnalysis:
        """Analyze failure patterns for an account.
        
        Args:
            account_id: Account ID
            
        Returns:
            Failure analysis
        """
        failures = self.list_by_account(account_id)
        
        if not failures:
            return FailureAnalysis(
                account_id=account_id,
                total_failures=0,
                failure_types={},
                failure_steps={},
                most_common_type="none",
                most_common_step="none",
                recommendation="No failures recorded"
            )
        
        # Count failure types and steps
        type_counts: dict[str, int] = {}
        step_counts: dict[str, int] = {}
        
        for f in failures:
            ft = f.failure_type.value
            fs = f.failure_step
            type_counts[ft] = type_counts.get(ft, 0) + 1
            step_counts[fs] = step_counts.get(fs, 0) + 1
        
        # Find most common
        most_common_type = max(type_counts.items(), key=lambda x: x[1])
        most_common_step = max(step_counts.items(), key=lambda x: x[1])
        
        # Generate recommendation
        recommendation = self._generate_recommendation(most_common_type[0], failures)
        
        return FailureAnalysis(
            account_id=account_id,
            total_failures=len(failures),
            failure_types=type_counts,
            failure_steps=step_counts,
            most_common_type=most_common_type[0],
            most_common_step=most_common_step[0],
            recommendation=recommendation
        )

    def _row_to_response(self, row: sqlite3.Row) -> FailureLogResponse:
        """Convert database row to response model."""
        state_data = None
        if row['state_data']:
            try:
                state_data = json.loads(row['state_data'])
            except json.JSONDecodeError:
                state_data = None
        
        return FailureLogResponse(
            failure_id=row['failure_id'],
            run_id=row['run_id'],
            thread_id=row['thread_id'],
            account_id=row['account_id'],
            failure_type=FailureType(row['failure_type']),
            failure_step=row['failure_step'],
            failure_reason=row['failure_reason'],
            state_data=state_data,
            created_at=row['created_at']
        )

    def _generate_recommendation(self, failure_type: str, failures: list) -> str:
        """Generate recommendation based on failure type."""
        if failure_type == "equipment":
            return "Consider checking equipment compatibility or assigning different model"
        elif failure_type == "network":
            return "Network issues detected. Consider dispatching technician"
        elif failure_type == "system":
            return "System error. Contact technical support"
        elif failure_type == "configuration":
            return "Configuration error. Review setup parameters"
        elif failure_type == "timeout":
            return "Operation timed out. Check network connectivity"
        else:
            return "Review failure logs for specific issues"
