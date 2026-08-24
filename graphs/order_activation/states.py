"""State definitions for Order-to-Activation Graph."""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional


class GraphState(str, Enum):
    """All possible states in the activation graph."""
    START = "start"
    CREATE_ACCOUNT = "create_account"
    VERIFY_IDENTITY = "verify_identity"
    CHECK_EQUIPMENT = "check_equipment"
    WAIT_FOR_EQUIPMENT = "wait_for_equipment"
    CONFIGURE_EQUIPMENT = "configure_equipment"
    HITL_WAIT = "hitl_wait"
    TEST_CONNECTION = "test_connection"
    ACTIVATE_SERVICE = "activate_service"
    SEND_WELCOME = "send_welcome"
    FAILURE = "failure"
    RETRY = "retry"
    END = "end"


@dataclass
class ActivationData:
    """Data passed between states in the graph."""
    account_id: Optional[int] = None
    customer_name: Optional[str] = None
    address: Optional[str] = None
    plan_id: Optional[int] = None
    pin: Optional[str] = None
    equipment_serial: Optional[str] = None
    equipment_model: Optional[str] = None
    equipment_status: Optional[str] = None
    verified: bool = False
    configured: bool = False
    tested: bool = False
    activated: bool = False
    ticket_id: Optional[int] = None
    thread_id: Optional[int] = None
    run_id: Optional[int] = None
    hitl_task_id: Optional[int] = None
    failure_reason: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    hitl_approved: bool = False
    hitl_reason: Optional[str] = None
    hitl_task_id: Optional[int] = None
    # Propagated from the graph runner so HITL and failure managers get real IDs
    run_id: Optional[int] = None
    thread_id: Optional[int] = None
    messages: list[dict[str, str]] = field(default_factory=list)
    current_step: str = ""
    error: Optional[str] = None

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        self.messages.append({"role": role, "content": content})

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "account_id": self.account_id,
            "customer_name": self.customer_name,
            "address": self.address,
            "plan_id": self.plan_id,
            "pin": self.pin,
            "equipment_serial": self.equipment_serial,
            "equipment_model": self.equipment_model,
            "equipment_status": self.equipment_status,
            "verified": self.verified,
            "configured": self.configured,
            "tested": self.tested,
            "activated": self.activated,
            "ticket_id": self.ticket_id,
            "thread_id": self.thread_id,
            "run_id": self.run_id,
            "hitl_task_id": self.hitl_task_id,
            "failure_reason": self.failure_reason,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "hitl_approved": self.hitl_approved,
            "hitl_reason": self.hitl_reason,
            "current_step": self.current_step,
            "error": self.error,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActivationData:
        """Create from dictionary (for checkpoint restoration)."""
        return cls(
            account_id=data.get("account_id"),
            customer_name=data.get("customer_name"),
            address=data.get("address"),
            plan_id=data.get("plan_id"),
            pin=data.get("pin"),
            equipment_serial=data.get("equipment_serial"),
            equipment_model=data.get("equipment_model"),
            equipment_status=data.get("equipment_status"),
            verified=data.get("verified", False),
            configured=data.get("configured", False),
            tested=data.get("tested", False),
            activated=data.get("activated", False),
            ticket_id=data.get("ticket_id"),
            failure_reason=data.get("failure_reason"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            hitl_approved=data.get("hitl_approved", False),
            hitl_reason=data.get("hitl_reason"),
            hitl_task_id=data.get("hitl_task_id"),
            run_id=data.get("run_id"),
            thread_id=data.get("thread_id"),
            current_step=data.get("current_step", ""),
            error=data.get("error"),
            messages=list(data.get("messages", [])),
        )
