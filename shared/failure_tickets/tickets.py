"""Ticket CRUD operations."""
from __future__ import annotations
import sqlite3
from datetime import datetime
from typing import Optional
from contextlib import contextmanager
from .models import (
    TicketCreate, TicketUpdate, TicketResponse,
    TicketStatus, TicketType
)


class TicketManager:
    """Manages ticket operations."""

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db_path = db_path

    @contextmanager
    def _get_conn(self):
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create(self, ticket: TicketCreate) -> TicketResponse:
        """Create a new ticket.
        
        Args:
            ticket: Ticket creation data
            
        Returns:
            Created ticket
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO SUPPORT_TICKETS 
                   (account_id, ticket_type, status, description)
                   VALUES (?, ?, ?, ?)""",
                (ticket.account_id, ticket.ticket_type.value, 
                 TicketStatus.OPEN.value, ticket.description)
            )
            ticket_id = cursor.lastrowid
            conn.commit()
            
            return self.get(ticket_id)

    def get(self, ticket_id: int) -> Optional[TicketResponse]:
        """Get a ticket by ID.
        
        Args:
            ticket_id: Ticket ID
            
        Returns:
            Ticket or None
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM SUPPORT_TICKETS WHERE ticket_id = ?",
                (ticket_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return TicketResponse(
                ticket_id=row['ticket_id'],
                account_id=row['account_id'],
                ticket_type=TicketType(row['ticket_type']),
                status=TicketStatus(row['status']),
                description=row['description'],
                created_at=row['created_at'],
                updated_at=row.get('updated_at')
            )

    def update(self, ticket_id: int, update: TicketUpdate) -> Optional[TicketResponse]:
        """Update a ticket.
        
        Args:
            ticket_id: Ticket ID
            update: Update data
            
        Returns:
            Updated ticket or None
        """
        with self._get_conn() as conn:
            # Build update query
            updates = []
            params = []
            
            if update.status is not None:
                updates.append("status = ?")
                params.append(update.status.value)
            
            if update.description is not None:
                updates.append("description = ?")
                params.append(update.description)
            
            if not updates:
                return self.get(ticket_id)
            
            updates.append("created_at = created_at")  # Keep original created_at
            params.append(ticket_id)
            
            conn.execute(
                f"UPDATE SUPPORT_TICKETS SET {', '.join(updates)} WHERE ticket_id = ?",
                params
            )
            conn.commit()
            
            return self.get(ticket_id)

    def delete(self, ticket_id: int) -> bool:
        """Delete a ticket.
        
        Args:
            ticket_id: Ticket ID
            
        Returns:
            True if deleted
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM SUPPORT_TICKETS WHERE ticket_id = ?",
                (ticket_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_by_account(self, account_id: int) -> list[TicketResponse]:
        """List all tickets for an account.
        
        Args:
            account_id: Account ID
            
        Returns:
            List of tickets
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM SUPPORT_TICKETS 
                   WHERE account_id = ?
                   ORDER BY created_at DESC""",
                (account_id,)
            ).fetchall()
            
            return [
                TicketResponse(
                    ticket_id=row['ticket_id'],
                    account_id=row['account_id'],
                    ticket_type=TicketType(row['ticket_type']),
                    status=TicketStatus(row['status']),
                    description=row['description'],
                    created_at=row['created_at'],
                )
                for row in rows
            ]

    def list_all(self, status: Optional[TicketStatus] = None) -> list[TicketResponse]:
        """List all tickets, optionally filtered by status.
        
        Args:
            status: Optional status filter
            
        Returns:
            List of tickets
        """
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    """SELECT * FROM SUPPORT_TICKETS 
                       WHERE status = ?
                       ORDER BY created_at DESC""",
                    (status.value,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM SUPPORT_TICKETS 
                       ORDER BY created_at DESC"""
                ).fetchall()
            
            return [
                TicketResponse(
                    ticket_id=row['ticket_id'],
                    account_id=row['account_id'],
                    ticket_type=TicketType(row['ticket_type']),
                    status=TicketStatus(row['status']),
                    description=row['description'],
                    created_at=row['created_at'],
                )
                for row in rows
            ]

    def count_by_status(self) -> dict[str, int]:
        """Count tickets by status.
        
        Returns:
            Dictionary of status counts
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM SUPPORT_TICKETS GROUP BY status"
            ).fetchall()
            
            return {row['status']: row['count'] for row in rows}
