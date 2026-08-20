"""Pydantic models for Failure/Ticket System."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    """Ticket status enum."""
    OPEN = "open"
    ONGOING = "ongoing"
    CLOSED = "closed"


class TicketType(str, Enum):
    """Ticket type enum."""
    BILLING = "billing"
    TECHNICAL = "technical"
    DISPATCH = "dispatch"
    OTHER = "other"


class FailureType(str, Enum):
    """Failure type enum."""
    EQUIPMENT = "equipment"
    NETWORK = "network"
    SYSTEM = "system"
    CONFIGURATION = "configuration"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class TicketCreate(BaseModel):
    """Model for creating a ticket."""
    account_id: int
    ticket_type: TicketType
    description: str = Field(min_length=1, max_length=1000)


class TicketUpdate(BaseModel):
    """Model for updating a ticket."""
    status: Optional[TicketStatus] = None
    description: Optional[str] = None


class TicketResponse(BaseModel):
    """Model for ticket response."""
    ticket_id: int
    account_id: int
    ticket_type: TicketType
    status: TicketStatus
    description: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class FailureLogCreate(BaseModel):
    """Model for creating a failure log."""
    run_id: int
    thread_id: int
    account_id: int
    failure_type: FailureType
    failure_step: str
    failure_reason: str
    state_data: Optional[dict[str, Any]] = None


class FailureLogResponse(BaseModel):
    """Model for failure log response."""
    failure_id: int
    run_id: int
    thread_id: int
    account_id: int
    failure_type: FailureType
    failure_step: str
    failure_reason: str
    state_data: Optional[dict[str, Any]] = None
    created_at: datetime


class FailureAnalysis(BaseModel):
    """Model for failure analysis."""
    account_id: int
    total_failures: int
    failure_types: dict[str, int]
    failure_steps: dict[str, int]
    most_common_type: str
    most_common_step: str
    recommendation: str


class RetryDecision(BaseModel):
    """Model for retry decision."""
    should_retry: bool
    retry_count: int
    max_retries: int
    ticket_id: Optional[int] = None
    failure_id: Optional[int] = None


class HealthResponse(BaseModel):
    """Model for health check response."""
    status: str = "healthy"
    service: str = "failure-ticket-system"
    version: str = "1.0.0"
