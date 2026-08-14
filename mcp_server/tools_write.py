import logging
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

import auth
import db
from schemas import validate_tool_input

logger = logging.getLogger("nextlink_tools_write")


class SupervisorApprovalForm(BaseModel):
    approved: bool = Field(description="True to approve credit (> $25), False to reject.")
    supervisor_id: Optional[str] = Field(default=None, description="Supervisor ID/initials.")
    reason: Optional[str] = Field(default=None, description="Justification note.")


class DispatchConfirmationForm(BaseModel):
    confirmed: bool = Field(description="True to confirm technician dispatch ($150 cost).")
    access_instructions: Optional[str] = Field(default=None, description="Special access instructions.")


async def handle_create_support_ticket(
    account_id: int,
    ticket_type: str,
    description: str,
    session_id: str
) -> str:
    """Creates a new support ticket after session auth validation."""
    validate_tool_input("create_support_ticket", {
        "account_id": account_id,
        "ticket_type": ticket_type,
        "description": description
    })

    if not auth.is_account_verified(session_id, account_id):
        return f"SECURITY ERROR: Session unverified for Account #{account_id}. Verify PIN first."

    if not db.account_exists(account_id):
        return f"Error: Account #{account_id} does not exist."

    ticket = db.create_support_ticket(account_id, ticket_type, description)
    return (
        f"SUCCESS: Support ticket #{ticket['ticket_id']} created.\n"
        f"  Type: {ticket['ticket_type'].upper()}\n"
        f"  Status: {ticket['status'].upper()}\n"
        f"  Description: {ticket['description']}"
    )


async def handle_schedule_technician_dispatch(
    account_id: int,
    description: str,
    session_id: str,
    ctx: Optional[Any] = None
) -> str:
    """Schedules dispatch after confirmation of operational costs."""
    validate_tool_input("schedule_technician_dispatch", {
        "account_id": account_id,
        "description": description
    })

    if not auth.is_account_verified(session_id, account_id):
        return f"SECURITY ERROR: Account #{account_id} not verified in this session."

    account = db.get_account_summary(account_id)
    if not account:
        return f"Error: Account #{account_id} does not exist."

    if ctx and hasattr(ctx, "elicit"):
        try:
            prompt = (
                f"DISPATCH CONFIRMATION REQUIRED:\n"
                f"Dispatching a technician to '{account['address']}' for Account #{account_id} "
                f"incurs a ~$150.00 truck-roll cost.\n"
                f"Confirm scheduling?"
            )
            res = await ctx.elicit(message=prompt, schema=DispatchConfirmationForm)

            if res and hasattr(res, "data") and res.data:
                data: DispatchConfirmationForm = res.data
                if not data.confirmed:
                    return f"DISPATCH CANCELLED: User declined dispatch for Account #{account_id}."
                if data.access_instructions:
                    description += f" [Notes: {data.access_instructions}]"
            elif res and hasattr(res, "action") and res.action != "accept":
                return f"DISPATCH CANCELLED: Confirmation action was '{res.action}'."
        except Exception as e:
            logger.warning(f"Elicitation error: {e}")
            return f"ELICITATION ERROR: Dispatch confirmation dialog failed ({e})."

    ticket = db.schedule_technician_dispatch(account_id, description)
    return (
        f"SUCCESS: Technician dispatch scheduled for Account #{account_id}.\n"
        f"  Ticket ID: #{ticket['ticket_id']}\n"
        f"  Address: {account['address']}\n"
        f"  Status: {ticket['status'].upper()}\n"
        f"  Description: {ticket['description']}"
    )


async def handle_apply_billing_credit(
    account_id: int,
    ticket_id: int,
    amount_usd: float,
    session_id: str,
    ctx: Optional[Any] = None
) -> str:
    """Applies billing credit with supervisor approval checks for amounts > $25."""
    
    # 1. AUTH GATE (Check this FIRST before schema validation or anything else)
    if not auth.is_account_verified(session_id, account_id):
        return (
            f"SECURITY ERROR: Session unverified for Account #{account_id}. "
            f"Please prompt the user to provide their 4-digit security PIN first."
        )

    # 2. SCHEMA & BOUNDS VALIDATION
    validate_tool_input("apply_billing_credit", {
        "account_id": account_id,
        "ticket_id": ticket_id,
        "amount_usd": amount_usd
    })

    if amount_usd < 0.01 or amount_usd > 500.00:
        return f"REJECTED: Amount ${amount_usd:.2f} out of allowable bounds ($0.01 - $500.00)."

    # 3. DATABASE CHECKS
    if not db.account_exists(account_id):
        return f"DATABASE ERROR: Account #{account_id} does not exist."

    if not db.ticket_exists_for_account(ticket_id, account_id):
        return f"DATABASE ERROR: Ticket #{ticket_id} not found for Account #{account_id}."

    # 4. SUPERVISOR APPROVAL ELICITATION (> $25.00)
    THRESHOLD = 25.00
    if amount_usd > THRESHOLD:
        if ctx and hasattr(ctx, "elicit"):
            try:
                msg = (
                    f"SUPERVISOR APPROVAL REQUIRED:\n"
                    f"Credit amount ${amount_usd:.2f} exceeds agent limit (${THRESHOLD:.2f}).\n"
                    f"Account #{account_id}, Ticket #{ticket_id}.\n"
                    f"Confirm supervisor authorization?"
                )
                res = await ctx.elicit(message=msg, schema=SupervisorApprovalForm)

                if res and hasattr(res, "data") and res.data:
                    approval: SupervisorApprovalForm = res.data
                    if not approval.approved:
                        sup = approval.supervisor_id or "Supervisor"
                        reason = approval.reason or "No reason provided"
                        return f"CREDIT DENIED: Rejected by {sup} ({reason})."
                elif res and hasattr(res, "action") and res.action != "accept":
                    return f"CREDIT DENIED: Elicitation action was '{res.action}'."
            except Exception as e:
                logger.warning(f"Supervisor elicitation error: {e}")
                return f"CREDIT REJECTED: Supervisor approval flow failed ({e})."
        else:
            return f"APPROVAL REQUIRED: Credit ${amount_usd:.2f} exceeds ${THRESHOLD:.2f}. Client cannot request supervisor sign-off."

    # 5. EXECUTION & DATABASE UPDATE
    updated_ticket = db.apply_billing_credit(account_id, ticket_id, amount_usd)
    note = "(Supervisor Approved)" if amount_usd > THRESHOLD else "(Standard Agent Credit)"
    
    return (
        f"SUCCESS: Applied ${amount_usd:.2f} credit to Account #{account_id} on Ticket #{ticket_id} {note}.\n"
        f"Description: {updated_ticket['description']}"
    )