"""Failure/Ticket Service - Orchestration layer."""
from __future__ import annotations
from typing import Optional, Any
from .models import (
    TicketCreate, TicketUpdate, TicketResponse, TicketStatus,
    FailureLogCreate, FailureLogResponse, FailureType,
    RetryDecision
)
from .tickets import TicketManager
from .failures import FailureManager


class FailureTicketService:
    """Orchestrates failure handling and ticket management."""

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db_path = db_path
        self.tickets = TicketManager(db_path)
        self.failures = FailureManager(db_path)

    def handle_failure(
        self,
        run_id: int,
        thread_id: int,
        account_id: int,
        failure_type: FailureType,
        failure_step: str,
        failure_reason: str,
        state_data: Optional[dict[str, Any]] = None,
        retry_count: int = 0,
        max_retries: int = 3
    ) -> RetryDecision:
        """Handle a failure: log it, create ticket, decide retry.
        
        Args:
            run_id: Current run ID
            thread_id: Current thread ID
            account_id: Account that failed
            failure_type: Type of failure
            failure_step: Step where failure occurred
            failure_reason: Why it failed
            state_data: State data at time of failure
            retry_count: Number of retries attempted
            max_retries: Maximum allowed retries
            
        Returns:
            Retry decision
        """
        # 1. Log the failure
        failure_log = self.failures.log(FailureLogCreate(
            run_id=run_id,
            thread_id=thread_id,
            account_id=account_id,
            failure_type=failure_type,
            failure_step=failure_step,
            failure_reason=failure_reason,
            state_data=state_data
        ))
        
        # 2. Create support ticket
        ticket = self.tickets.create(TicketCreate(
            account_id=account_id,
            ticket_type=self._failure_type_to_ticket_type(failure_type),
            description=f"Activation Failure: {failure_type.value}\n"
                       f"Step: {failure_step}\n"
                       f"Reason: {failure_reason}"
        ))
        
        # 3. Decide retry
        should_retry = retry_count < max_retries
        
        return RetryDecision(
            should_retry=should_retry,
            retry_count=retry_count,
            max_retries=max_retries,
            ticket_id=ticket.ticket_id,
            failure_id=failure_log.failure_id
        )

    def resolve_ticket(
        self,
        ticket_id: int,
        resolution: str = "Resolved"
    ) -> Optional[TicketResponse]:
        """Resolve a ticket.
        
        Args:
            ticket_id: Ticket ID
            resolution: Resolution notes
            
        Returns:
            Updated ticket
        """
        return self.tickets.update(ticket_id, TicketUpdate(
            status=TicketStatus.CLOSED,
            description=resolution
        ))

    def get_ticket_details(self, ticket_id: int) -> Optional[TicketResponse]:
        """Get ticket details.
        
        Args:
            ticket_id: Ticket ID
            
        Returns:
            Ticket details
        """
        return self.tickets.get(ticket_id)

    def list_account_tickets(self, account_id: int) -> list[TicketResponse]:
        """List all tickets for an account.
        
        Args:
            account_id: Account ID
            
        Returns:
            List of tickets
        """
        return self.tickets.list_by_account(account_id)

    def list_open_tickets(self) -> list[TicketResponse]:
        """List all open tickets.
        
        Returns:
            List of open tickets
        """
        return self.tickets.list_all(TicketStatus.OPEN)

    def get_failure_analysis(self, account_id: int):
        """Get failure analysis for an account.
        
        Args:
            account_id: Account ID
            
        Returns:
            Failure analysis
        """
        return self.failures.analyze(account_id)

    def get_ticket_stats(self) -> dict[str, int]:
        """Get ticket statistics.
        
        Returns:
            Ticket counts by status
        """
        return self.tickets.count_by_status()

    def _failure_type_to_ticket_type(self, failure_type: FailureType):
        """Map failure type to ticket type."""
        from .models import TicketType
        
        mapping = {
            FailureType.EQUIPMENT: TicketType.TECHNICAL,
            FailureType.NETWORK: TicketType.TECHNICAL,
            FailureType.SYSTEM: TicketType.TECHNICAL,
            FailureType.CONFIGURATION: TicketType.TECHNICAL,
            FailureType.TIMEOUT: TicketType.TECHNICAL,
            FailureType.UNKNOWN: TicketType.OTHER,
        }
        
        return mapping.get(failure_type, TicketType.OTHER)
