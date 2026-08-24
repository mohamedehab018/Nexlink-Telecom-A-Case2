"""State-graph agents reachable from the chat switcher.

  billing  -> graphs/sla_dispute LangGraph (pauses on a real interrupt until
              an admin approves/rejects through the platform's HITL API)
  dispatch -> graphs/order_activation ActivationGraph (slot-filling chat
              front end; pauses at HITL_WAIT for equipment-cost approval)

Both run against the same shared db/nexlink.db and MCP-era tables — no
parallel database is created.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
DB = str(ROOT / "db" / "nexlink.db")


# ---------------------------------------------------------------------------
# Billing agent — SLA-dispute state graph
# ---------------------------------------------------------------------------

_sla_graph: Any = None
# Review tasks whose outcome has already been announced in the chat, so a
# finished thread is summarized once instead of re-reporting forever.
_sla_reported: set[tuple[str, int]] = set()


def _get_sla_graph():
    global _sla_graph
    if _sla_graph is None:
        from graphs.sla_dispute.graph import build_sla_dispute_graph

        _sla_graph = build_sla_dispute_graph()
    return _sla_graph


def _sla_config(session_id: str) -> dict:
    # One durable LangGraph thread per chat session.
    return {"configurable": {"thread_id": f"chat-{session_id}"}}


def _extract_account_id(message: str) -> Optional[int]:
    m = re.search(r"account\s*#?\s*(\d+)", message, re.IGNORECASE)
    return int(m.group(1)) if m else None


def run_billing_agent(
    session_id: str, message: str, active_account_id: Optional[str] = None
) -> str:
    """Route one chat turn into the SLA-dispute graph.

    Resumes an interrupted (HITL-paused) thread when the admin has decided,
    reports 'pending' while the task is open, or starts a new dispute run.
    """
    from langgraph.types import Command

    from graphs.sla_dispute.hitl_tasks import hitl_task_manager

    graph = _get_sla_graph()
    config = _sla_config(session_id)
    snapshot = graph.get_state(config)

    # --- existing paused thread? -----------------------------------------
    if snapshot and snapshot.next:
        values = snapshot.values or {}
        task_id = values.get("hitl_task_id")
        task = hitl_task_manager.get_task(task_id) if task_id else None
        if task is None:
            return (
                "Your dispute review is waiting for an administrator, but its "
                "review task could not be found. Please start a new dispute."
            )
        if task.status == "pending":
            return (
                f"Your SLA dispute (task #{task.task_id}) is still pending "
                f"administrator review on the admin console. I'll pick up "
                f"their decision as soon as it's made."
            )

        decision = (task.decision or "").strip().lower()
        if decision not in {"approve", "reject"}:
            return f"Review task #{task.task_id} has an unrecognized status; please contact support."

        result = graph.invoke(Command(resume=decision), config=config)
        final = result if isinstance(result, dict) else (getattr(result, "values", {}) or {})
        ticket = final.get("failure_ticket_id")
        if decision == "approve":
            return (
                f"The administrator approved your dispute (task #{task.task_id}). "
                f"{final.get('liability_reasoning', '').strip() or ''}".strip()
                or f"Dispute approved (task #{task.task_id})."
            )
        return (
            f"The administrator rejected your dispute (task #{task.task_id}): "
            f"{final.get('error') or 'resolution denied'}."
            + (f" A failure ticket (#{ticket}) was opened." if ticket else "")
        )

    # --- finished thread whose outcome hasn't been announced yet? ----------
    # The admin decided through the platform, which resumed and completed
    # the thread; deliver the verdict here on the user's next message.
    if snapshot and snapshot.values:
        values = snapshot.values
        task_id = values.get("hitl_task_id")
        decided_task = hitl_task_manager.get_task(task_id) if task_id else None
        if decided_task and decided_task.status != "pending":
            key = (session_id, decided_task.task_id)
            if key not in _sla_reported:
                _sla_reported.add(key)
                if decided_task.decision == "approve":
                    return (
                        f"Update on your SLA dispute (task #{decided_task.task_id}): "
                        f"the administrator approved it."
                        + (
                            f" {values.get('liability_reasoning', '').strip()}"
                            if values.get("liability_reasoning") else ""
                        )
                    )
                ticket = values.get("failure_ticket_id")
                return (
                    f"Update on your SLA dispute (task #{decided_task.task_id}): "
                    f"the administrator rejected it — {values.get('error') or 'resolution denied'}."
                    + (f" A failure ticket (#{ticket}) was opened." if ticket else "")
                )

    # --- new dispute -------------------------------------------------------
    customer_id = _extract_account_id(message)
    if customer_id is None and active_account_id:
        try:
            customer_id = int(active_account_id)
        except (TypeError, ValueError):
            customer_id = None
    claim = message.strip()
    if not claim:
        claim = "SLA dispute"

    if customer_id is None:
        return (
            "I can dispute an SLA breach for you. Which account is it for? "
            "Include your account number (for example, 'dispute my SLA for "
            "account 1 because my internet was down for two days')."
        )

    try:
        result = graph.invoke(
            {
                "run_id": f"chat-{session_id}",
                "customer_id": customer_id,
                "claim_details": claim,
            },
            config=config,
        )
    except ValueError as exc:
        return f"I couldn't file that dispute: {exc}"

    # A plain-dict result includes "__interrupt__" when the graph paused at
    # its HITL node; otherwise it's the final state values.
    if isinstance(result, dict):
        was_interrupted = "__interrupt__" in result
        final = {k: v for k, v in result.items() if k != "__interrupt__"}
    else:
        was_interrupted = False
        final = getattr(result, "values", {}) or {}
    task_id = final.get("hitl_task_id")

    if was_interrupted or task_id:
        reasoning = (final.get("liability_reasoning") or "").strip()
        liability = final.get("liability_decision") or "undetermined"
        parts = [
            f"I analyzed your dispute against account #{customer_id}.",
            f"Preliminary finding: liability {liability}."
            + (f" {reasoning}" if reasoning else ""),
        ]
        if task_id:
            parts.append(
                f"This needs administrator sign-off before resolution — review "
                f"task #{task_id} is now pending on the admin console. You'll "
                f"get the outcome here once they decide."
            )
        return "\n\n".join(parts)

    # Ran straight through with no HITL (unexpected but handled)
    return (
        f"Your dispute for account #{customer_id} was resolved automatically. "
        f"Outcome: {final.get('liability_decision') or 'recorded'}."
    )


# ---------------------------------------------------------------------------
# Dispatch agent — order-activation state graph (conversational slot filling)
# ---------------------------------------------------------------------------

_REQUIRED_SLOTS = ("customer_name", "address", "plan_id", "pin")

_pending_dispatch: dict[str, dict[str, Any]] = {}

_activation_graph: Any = None


def _get_activation_graph():
    global _activation_graph
    if _activation_graph is None:
        from graphs.order_activation.graph import ActivationGraph

        _activation_graph = ActivationGraph(DB)
    return _activation_graph


def _extract_slots(message: str, slots: dict[str, Any]) -> list[str]:
    """Pull activation details out of free text; returns newly filled slots."""
    filled = []

    if "plan_id" not in slots:
        m = re.search(r"plan\s*#?\s*(\d+)", message, re.IGNORECASE)
        if m:
            slots["plan_id"] = int(m.group(1))
            filled.append("plan_id")

    if "pin" not in slots:
        m = re.search(r"\bpin\b\s*(?:is\s*)?[#:]*\s*(\d{4})", message, re.IGNORECASE)
        if m:
            slots["pin"] = m.group(1)
            filled.append("pin")

    if "address" not in slots:
        m = re.search(
            r"(?:\bat\b|\baddress(?:\s+is)?\b)\s+([0-9][A-Za-z0-9 ,'./#-]{2,60})"
            r"(?=\s+plan\b|[,.]|$)",
            message,
            re.IGNORECASE,
        )
        if m:
            slots["address"] = m.group(1).strip(" ,.")
            filled.append("address")

    if "customer_name" not in slots:
        m = re.search(
            r"(?:\bfor\b|\bname(?:'s)?\s+(?:is)?:?\s)\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})",
            message,
        )
        if not m:
            m = re.search(r"\bactivate\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})", message)
        if m:
            name = m.group(1).strip()
            if name.lower() not in {"service", "internet", "plan"}:
                slots["customer_name"] = name
                filled.append("customer_name")

    return filled


def run_dispatch_agent(session_id: str, message: str) -> str:
    """Route one chat turn into the order-activation graph."""
    slots = _pending_dispatch.setdefault(session_id, {})
    _extract_slots(message, slots)

    missing = [s for s in _REQUIRED_SLOTS if s not in slots]

    if missing:
        labels = {
            "customer_name": "the customer's full name (e.g. 'for John Smith')",
            "address": "the installation address (e.g. 'at 5 New St')",
            "plan_id": "the plan number (e.g. 'plan 2')",
            "pin": "the 4-digit PIN (e.g. 'PIN 1234')",
        }
        return (
            "Sure — I can activate a new service connection. I still need:\n"
            + "\n".join(f"• {labels[s]}" for s in missing)
            + "\n\nSend the details in one message or several."
        )

    graph = _get_activation_graph()
    try:
        result = graph.run(
            customer_name=slots["customer_name"],
            address=slots["address"],
            plan_id=int(slots["plan_id"]),
            pin=str(slots["pin"]),
        )
    except Exception as exc:  # noqa: BLE001 — surface as a normal reply
        _pending_dispatch.pop(session_id, None)
        return f"The activation graph hit an unexpected error: {exc}"

    if result.get("paused"):
        return (
            f"I've queued the activation for {slots['customer_name']} "
            f"(account #{result.get('account_id')}). It needs supervisor "
            f"approval first — HITL task #{result.get('task_id')} is now "
            f"pending on the admin console, and the graph will resume from "
            f"its checkpoint once they decide."
        )

    _pending_dispatch.pop(session_id, None)
    data = result.get("data", {})
    if result.get("success"):
        return (
            f"Activation complete for {slots['customer_name']}!\n"
            f"• Account #{result.get('account_id')}\n"
            f"• Equipment: {data.get('equipment_serial', 'n/a')}\n"
            f"• Service activated and welcome message sent."
        )
    ticket_id = result.get("ticket_id")
    ticket_note = f" (ticket #{ticket_id})" if ticket_id else ""
    return (
        f"The activation could not be completed{ticket_note}: "
        f"{result.get('error') or data.get('failure_reason') or 'unknown failure'}."
    )
