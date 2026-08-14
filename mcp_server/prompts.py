from typing import Any, Dict, List
import db


def generate_draft_outage_explanation_messages(account_id: int, ticket_id: int) -> List[Dict[str, str]]:
    """Builds prompt messages for drafting customer outage communications."""
    account = db.get_account_summary(account_id)
    if not account:
        account_info = f"Account #{account_id} (Customer details unavailable)"
    else:
        account_info = f"Customer: {account['customer_name']} (Account #{account_id}, Plan: {account['plan_name']})"

    ticket = db.get_ticket_by_id(ticket_id)
    if not ticket or ticket.get("account_id") != account_id:
        ticket_info = f"Ticket #{ticket_id} (No details found for this account)"
    else:
        ticket_info = (
            f"Ticket #{ticket['ticket_id']} [{ticket['ticket_type'].upper()}]\n"
            f"Status: {ticket['status'].upper()}\n"
            f"Created: {ticket['created_at']}\n"
            f"Description: {ticket['description']}"
        )

    equipment = db.get_equipment_by_account(account_id)
    if not equipment:
        eq_info = "No registered equipment records found."
    else:
        eq_lines = [
            f"- Serial: {eq['serial_num']} | Model: {eq['model_type']} | Status: {eq['status'].upper()}\n"
            f"  Log: {eq['last_error_log'] or 'None'}"
            for eq in equipment
        ]
        eq_info = "\n".join(eq_lines)

    prompt_content = f"""You are a customer support agent for Nextlink ISP.
Draft a clear, polite message explaining an outage/service issue using database records below:

--- ACCOUNT DETAILS ---
{account_info}

--- TICKET DETAILS ---
{ticket_info}

--- EQUIPMENT DIAGNOSTICS ---
{eq_info}

--- GUIDELINES ---
1. Address customer by name.
2. Explain technical issue in plain terms using equipment logs.
3. Provide current status (dispatch scheduled, line sweep, etc.).
4. Reassure customer and outline next steps.
"""

    return [{"role": "user", "content": prompt_content}]