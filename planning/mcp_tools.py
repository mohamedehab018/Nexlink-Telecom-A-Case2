"""Real MCP tool execution for the planning agent.

This is the wiring that turns DAG / dynamic-decomposition sub-task nodes into
genuine Nexlink tool calls: the exact same handlers, database, auth gate and
input schemas as the live MCP server in mcp_server/. A node with
kind="tool" names one of the tools below; the executor validates the
arguments, runs the real handler, and returns the exact string a client
would see over the wire -- including the SECURITY ERROR the auth gate returns
for an unverified write session.

`server.py` is imported directly so every tool call is byte-for-byte the same
function the FastMCP server registers (verify_account_identity, the read
tools and the write tools are all defined there).
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MCP_SERVER_DIR = os.path.abspath(os.path.join(_REPO_ROOT, "mcp_server"))
for _p in (_REPO_ROOT, _MCP_SERVER_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import auth  # noqa: E402  (mcp_server/auth.py)
import schemas  # noqa: E402  (mcp_server/schemas.py)
import server  # noqa: E402  (mcp_server/server.py)

WRITE_TOOLS = {
    "create_support_ticket",
    "schedule_technician_dispatch",
    "apply_billing_credit",
}


class _ElicitResult:
    """Shape of a client-side form response, as produced by FastMCP's ctx.elicit."""

    def __init__(self, data: Any):
        self.data = data
        self.action = "accept"


class _Elicit:
    """Stands in for the client side of the server's confirmation dialogs.

    schedule_technician_dispatch elicits a DispatchConfirmationForm (~$150
    truck-roll) and apply_billing_credit elicits a SupervisorApprovalForm
    (credits > $25). The agent-driven demo/eval can auto-accept or auto-deny
    through the constructor flags so the real handlers run end to end.
    """

    def __init__(self, dispatch_confirmed: bool = True, supervisor_approved: bool = True):
        self.dispatch_confirmed = dispatch_confirmed
        self.supervisor_approved = supervisor_approved

    async def __call__(self, message: str, schema: Any) -> _ElicitResult:
        name = getattr(schema, "__name__", "")
        if name == "DispatchConfirmationForm":
            data = schema(confirmed=self.dispatch_confirmed)
        elif name == "SupervisorApprovalForm":
            data = schema(
                approved=self.supervisor_approved,
                supervisor_id="PLANNING-AGENT",
                reason="Automated resolution run.",
            )
        else:
            data = schema()
        return _ElicitResult(data)


class ResolutionContext:
    """A minimal session context so the server handlers behave as in a live
    MCP session: `request_id` drives auth.get_session_id, `report_progress`
    is a no-op, and `elicit` resolves the confirmation dialogs.

    Deliberately has NO `session` attribute: auth.get_session_id prefers
    `str(id(ctx.session))`, which is a recyclable memory address, over
    `request_id`. Fixing `request_id` to the executor's session id is what
    keeps the auth gate scoped to one executor instance.
    """

    def __init__(
        self,
        session_id: str,
        dispatch_confirmed: bool = True,
        supervisor_approved: bool = True,
    ):
        self.request_id = session_id
        self._elicit = _Elicit(dispatch_confirmed, supervisor_approved)

    async def elicit(self, message: str, schema: Any) -> _ElicitResult:
        return await self._elicit(message, schema)

    async def report_progress(self, progress: int, total: int, message: str) -> None:
        pass


class MCPToolExecutor:
    """Executes a named Nexlink MCP tool against the real server handlers.

    Every call is schema-validated (mcp_server/schemas.py), hits the real
    database (mcp_server/db.py, NEXLINK_DB_PATH honoured) and is subject to
    the real session auth gate (mcp_server/auth.py). `call_log` records the
    exact trace a grader can inspect: tool, arguments, and result per call.
    """

    def _unwrap(fn: Any) -> Callable[..., str]:
        """FastMCP's @mcp.tool returns a FunctionTool wrapper; call the real handler."""
        return getattr(fn, "fn", fn)

    SYNC_TOOLS: Dict[str, Callable[..., str]] = {
        "get_account_summary": _unwrap(server.get_account_summary),
        "list_support_tickets": _unwrap(server.list_support_tickets),
        "get_equipment_diagnostics": _unwrap(server.get_equipment_diagnostics),
        "search_account_by_name": _unwrap(server.search_account_by_name),
    }

    ASYNC_TOOLS: Dict[str, Callable[..., str]] = {
        "verify_account_identity": _unwrap(server.verify_account_identity),
        "diagnose_equipment_issue": _unwrap(server.diagnose_equipment_issue),
        "run_network_diagnostic_sweep": _unwrap(server.run_network_diagnostic_sweep),
        "create_support_ticket": _unwrap(server.create_support_ticket),
        "schedule_technician_dispatch": _unwrap(server.schedule_technician_dispatch),
        "apply_billing_credit": _unwrap(server.apply_billing_credit),
    }

    def __init__(
        self,
        session_id: str = "planning-agent",
        dispatch_confirmed: bool = True,
        supervisor_approved: bool = True,
    ):
        auth.clear_session(session_id)
        self.session_id = session_id
        self.ctx = ResolutionContext(session_id, dispatch_confirmed, supervisor_approved)
        self.call_log: List[Dict[str, Any]] = []

    def call(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Validate and run a real tool, returning the exact server response."""
        args = dict(args or {})
        schemas.validate_tool_input(tool_name, args)
        if tool_name in self.SYNC_TOOLS:
            result = self.SYNC_TOOLS[tool_name](**args)
        elif tool_name in self.ASYNC_TOOLS:
            result = asyncio.run(self.ASYNC_TOOLS[tool_name](**args, ctx=self.ctx))
        else:
            raise ValueError(f"Unknown MCP tool '{tool_name}'")
        self.call_log.append({"tool": tool_name, "args": args, "result": result})
        return result

    @property
    def call_count(self) -> int:
        return len(self.call_log)
