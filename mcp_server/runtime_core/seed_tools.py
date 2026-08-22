"""Seed the mcp_tools table with all existing tools from the codebase."""
import sys
sys.path.insert(0, "/home/youssef/youssef/programming/college training/Nexlink-Telecom")

from mcp_server.runtime_core.db import MCPToolDatabase
from mcp_server.runtime_core.models import ToolDefinition

db = MCPToolDatabase()
db.init_db()

TOOLS = [
    # READ tools
    ("get_account_summary", "Fetch customer account summary (excludes sensitive PIN)", "read", "account"),
    ("list_support_tickets", "List all support tickets for a given account ID", "read", "ticket"),
    ("get_equipment_diagnostics", "Retrieve status and error logs for customer equipment", "read", "equipment"),
    ("search_account_by_name", "Search for account ID by full or partial customer name", "read", "account"),
    ("lookup_outage_incident", "Get account and prior-ticket evidence for an outage graph", "read", "network"),
    ("check_equipment_available", "Check if equipment is available for assignment", "read", "equipment"),

    # DIAGNOSTIC tools
    ("diagnose_equipment_issue", "Analyze raw error logs using client LLM sampling", "diagnostic", "equipment"),
    ("run_network_diagnostic_sweep", "Run multi-stage network test with live progress updates", "diagnostic", "network"),
    ("outage_equipment_diagnostics", "Structured equipment evidence for outage diagnosis", "diagnostic", "equipment"),
    ("outage_network_sweep", "Structured line/network sweep for outage diagnosis", "diagnostic", "network"),
    ("outage_resolution_check", "Verify current equipment state after outage remediation", "diagnostic", "network"),

    # WRITE tools
    ("create_support_ticket", "Open a new support ticket. Requires PIN verification", "write", "ticket"),
    ("schedule_technician_dispatch", "Schedule technician visit. Requires confirmation due to $150 cost", "dispatch", "equipment"),
    ("apply_billing_credit", "Apply credit to account. Amounts over $25 require supervisor sign-off", "billing", "account"),
    ("create_account", "Create a new customer account in the system", "write", "account"),
    ("assign_equipment", "Assign equipment to a customer account", "write", "equipment"),
    ("configure_equipment", "Configure equipment settings for a customer", "write", "equipment"),
    ("activate_service", "Activate internet service for a customer account", "write", "account"),
    ("send_welcome_message", "Send welcome message to newly activated customer", "write", "account"),

    # ADMIN tools
    ("verify_account_identity", "Verify account PIN to unlock write permissions for session", "admin", "account"),
]

for name, desc, cap, cat in TOOLS:
    try:
        db.create_tool(ToolDefinition(
            name=name,
            description=desc,
            capability=cap,
            category=cat,
            enabled=True,
            version="1.0.0",
            author="system",
        ))
        print(f"  + {name}")
    except Exception as e:
        print(f"  ! {name}: {e}")

print(f"\nSeeded {len(TOOLS)} tools.")
