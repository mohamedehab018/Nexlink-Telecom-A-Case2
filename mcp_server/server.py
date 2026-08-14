import argparse
import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Load .env directly here (not just in agent.py) so NEXLINK_DB_PATH and any
# other env vars are respected regardless of how the server is launched --
# `python server.py`, `mcp dev server.py`, or spawned as a subprocess by
# agent.py. Previously only agent.py called load_dotenv(), so running the
# server any other way silently ignored .env entirely.
load_dotenv()

from fastmcp import FastMCP, Context
import auth
import db
from prompts import generate_draft_outage_explanation_messages
from resources import get_credit_policy_resource, get_subscription_plans_resource
from schemas import validate_tool_input
import tools_diagnostic
import tools_read
import tools_write

# Logging setup (use stderr so we don't interfere with stdio communication)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("nextlink_mcp_server")
logger.info(f"Using database at: {db.get_db_path()}")

# Initialize MCP Server instance
mcp = FastMCP(
    "Nextlink ISP Support Assistant Server",
    instructions=(
        "You are an AI support assistant for Nextlink, a residential ISP. "
        "Help support staff inspect account status, run diagnostics, and manage tickets. "
        "Verification is required for write actions."
    ),
)


# --- READ-ONLY TOOLS ---

@mcp.tool(
    name="get_account_summary",
    description="Fetch customer account summary (excludes sensitive PIN)."
)
def get_account_summary(account_id: int) -> str:
    return tools_read.handle_get_account_summary(account_id)


@mcp.tool(
    name="list_support_tickets",
    description="List all support tickets for a given account ID."
)
def list_support_tickets(account_id: int) -> str:
    return tools_read.handle_list_support_tickets(account_id)


@mcp.tool(
    name="get_equipment_diagnostics",
    description="Retrieve status and error logs for customer equipment."
)
def get_equipment_diagnostics(account_id: int) -> str:
    return tools_read.handle_get_equipment_diagnostics(account_id)


@mcp.tool(
    name="search_account_by_name",
    description="Search for account ID by full or partial customer name (e.g., 'Walter White')."
)
def search_account_by_name(customer_name: str) -> str:
    validate_tool_input("search_account_by_name", {"customer_name": customer_name})
    account = db.search_account_by_name(customer_name)
    if not account:
        return f"No customer account found matching name '{customer_name}'."
    return (
        f"Found Customer: {account['customer_name']}\n"
        f"Account ID: {account['account_id']}\n"
        f"Address: {account['address']}"
    )


# --- AUTHENTICATION ---

@mcp.tool(
    name="verify_account_identity",
    description="Verify account PIN to unlock write permissions for session."
)
async def verify_account_identity(account_id: int, account_pin: int, ctx: Context) -> str:
    validate_tool_input("verify_account_identity", {"account_id": account_id, "account_pin": account_pin})
    
    if not db.account_exists(account_id):
        return f"VERIFICATION FAILED: Account #{account_id} does not exist."
    
    if not db.verify_account_pin(account_id, account_pin):
        logger.warning(f"Failed PIN attempt for Account #{account_id}")
        return f"VERIFICATION FAILED: Incorrect PIN for Account #{account_id}."
    
    session_id = auth.get_session_id(ctx)
    auth.mark_account_verified(session_id, account_id)
    
    if hasattr(ctx, "session") and hasattr(ctx.session, "send_tool_list_changed"):
        try:
            await ctx.session.send_tool_list_changed()
        except Exception as e:
            logger.warning(f"Failed to send tool list update: {e}")
    
    return f"VERIFICATION SUCCESSFUL: Session authorized for Account #{account_id}."


# --- DIAGNOSTICS ---

@mcp.tool(
    name="diagnose_equipment_issue",
    description="Analyze raw error logs using client LLM sampling."
)
async def diagnose_equipment_issue(serial_num: str, ctx: Context) -> str:
    return await tools_diagnostic.handle_diagnose_equipment_issue(serial_num, ctx=ctx)


@mcp.tool(
    name="run_network_diagnostic_sweep",
    description="Run multi-stage network test with live progress updates."
)
async def run_network_diagnostic_sweep(account_id: int, ctx: Context) -> str:
    return await tools_diagnostic.handle_run_network_diagnostic_sweep(account_id, ctx=ctx)


# --- WRITE OPERATIONS ---

@mcp.tool(
    name="create_support_ticket",
    description="Open a new support ticket. Requires PIN verification."
)
async def create_support_ticket(account_id: int, ticket_type: str, description: str, ctx: Context) -> str:
    session_id = auth.get_session_id(ctx)
    return await tools_write.handle_create_support_ticket(
        account_id=account_id,
        ticket_type=ticket_type,
        description=description,
        session_id=session_id
    )


@mcp.tool(
    name="schedule_technician_dispatch",
    description="Schedule technician visit. Requires confirmation due to $150 cost."
)
async def schedule_technician_dispatch(account_id: int, description: str, ctx: Context) -> str:
    session_id = auth.get_session_id(ctx)
    return await tools_write.handle_schedule_technician_dispatch(
        account_id=account_id,
        description=description,
        session_id=session_id,
        ctx=ctx
    )


@mcp.tool(
    name="apply_billing_credit",
    description="Apply credit to account. Amounts over $25 require supervisor sign-off."
)
async def apply_billing_credit(account_id: int, ticket_id: int, amount_usd: float, ctx: Context) -> str:
    session_id = auth.get_session_id(ctx)
    return await tools_write.handle_apply_billing_credit(
        account_id=account_id,
        ticket_id=ticket_id,
        amount_usd=amount_usd,
        session_id=session_id,
        ctx=ctx
    )


# --- RESOURCES & PROMPTS ---

@mcp.resource("nextlink://subscription-plans")
def resource_subscription_plans() -> str:
    return get_subscription_plans_resource()


@mcp.resource("nextlink://credit-policy")
def resource_credit_policy() -> str:
    return get_credit_policy_resource()


@mcp.prompt(name="draft_outage_explanation")
def prompt_draft_outage_explanation(account_id: int, ticket_id: int) -> List[Dict[str, str]]:
    return generate_draft_outage_explanation_messages(account_id, ticket_id)


# --- SERVER RUNNER ---

def main():
    parser = argparse.ArgumentParser(description="Nextlink MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    
    args = parser.parse_args()
    
    if args.transport == "stdio":
        logger.info("Starting Nextlink MCP Server (STDIO)...")
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting Nextlink MCP Server (HTTP) on {args.host}:{args.port}...")
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()