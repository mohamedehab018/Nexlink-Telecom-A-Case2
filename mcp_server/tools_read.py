from db import account_exists, get_account_summary, get_equipment_by_account, list_support_tickets
from schemas import validate_tool_input


def handle_get_account_summary(account_id: int) -> str:
    """Retrieves formatted account summary."""
    validate_tool_input("get_account_summary", {"account_id": account_id})

    if not account_exists(account_id):
        return f"Error: Account #{account_id} not found."

    account = get_account_summary(account_id)
    if not account:
        return f"Error: Could not fetch account details for #{account_id}."

    return (
        f"--- Account Summary (ID: {account['account_id']}) ---\n"
        f"Customer: {account['customer_name']}\n"
        f"Address: {account['address']}\n"
        f"Plan: {account['plan_name']} (${account['monthly_cost_usd']:.2f}/mo, up to {account['max_speed_mbps']} Mbps)\n"
    )


def handle_list_support_tickets(account_id: int) -> str:
    """Retrieves formatted list of support tickets."""
    validate_tool_input("list_support_tickets", {"account_id": account_id})

    if not account_exists(account_id):
        return f"Error: Account #{account_id} not found."

    tickets = list_support_tickets(account_id)
    if not tickets:
        return f"No support tickets found for account #{account_id}."

    lines = [f"--- Support Tickets for Account #{account_id} ({len(tickets)} total) ---"]
    for t in tickets:
        lines.append(
            f"Ticket #{t['ticket_id']} [{t['ticket_type'].upper()}] - Status: {t['status'].upper()}\n"
            f"  Created: {t['created_at']}\n"
            f"  Description: {t['description']}"
        )
    return "\n\n".join(lines)


def handle_get_equipment_diagnostics(account_id: int) -> str:
    """Retrieves registered hardware equipment status."""
    validate_tool_input("get_equipment_diagnostics", {"account_id": account_id})

    if not account_exists(account_id):
        return f"Error: Account #{account_id} not found."

    equipment_list = get_equipment_by_account(account_id)
    if not equipment_list:
        return f"No equipment assigned to account #{account_id}."

    lines = [f"--- Equipment Diagnostics for Account #{account_id} ---"]
    for eq in equipment_list:
        lines.append(
            f"Serial: {eq['serial_num']}\n"
            f"  Model: {eq['model_type']}\n"
            f"  Status: {eq['status'].upper()}\n"
            f"  Last Log: {eq['last_error_log'] or 'None'}"
        )
    return "\n\n".join(lines)