"""Chat endpoints wrapping the Nextlink support agent.

Replaces planning_agent.py's interactive ``input()`` loop with HTTP:
  - POST /api/chat/send                  -> one agent turn (4c)
  - GET  /api/chat/history/{session_id}  -> durable per-session history (4d)
  - GET  /api/chat/sessions              -> session index

Session state:
  - Durable history lives in ``chat_sessions``/``chat_messages`` tables.
  - In-process rolling memory (MemorySystem) is isolated per session so
    concurrent users never see each other's short-term context.
"""
from __future__ import annotations
import asyncio
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.llm_pacer import get_pacer
from agent.planning_agent import create_support_agent
from memory import MemorySystem

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]
# Tests point NEXLINK_CHAT_DB at a temp database so the live one stays untouched.
DB_PATH = os.getenv("NEXLINK_CHAT_DB") or str(ROOT / "db" / "nexlink.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatStore:
    """Durable chat sessions + messages."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'anonymous',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
                );
            """)

    def ensure_session(self, session_id: str, user_id: str = "anonymous") -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO chat_sessions(session_id,user_id,created_at) VALUES(?,?,?) "
                "ON CONFLICT(session_id) DO NOTHING",
                (session_id, user_id, _now()),
            )

    def session_exists(self, session_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM chat_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            return row is not None

    def append(self, session_id: str, role: str, content: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                (session_id, role, content, _now()),
            )

    def history(self, session_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM chat_messages "
                "WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def sessions(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT s.session_id, s.user_id, s.created_at, COUNT(m.id) AS message_count, "
                "(SELECT content FROM chat_messages c WHERE c.session_id=s.session_id "
                " AND c.role='user' ORDER BY c.id LIMIT 1) AS first_message "
                "FROM chat_sessions s LEFT JOIN chat_messages m ON m.session_id = s.session_id "
                "GROUP BY s.session_id ORDER BY s.created_at DESC"
            ).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                # Sidebar label: opening question of the conversation.
                title = (item.pop("first_message") or "").strip()
                item["title"] = title[:60] + ("…" if len(title) > 60 else "") or "Untitled chat"
                result.append(item)
            return result


chat_store = ChatStore(DB_PATH)

# One shared agent (LLM + RAG + MCP tools are expensive to build), built lazily
# on first use; per-session MemorySystem instances keep rolling context isolated.
_agent: Any | None = None
_agent_lock = asyncio.Lock()
_session_states: dict[str, dict[str, Any]] = {}


async def get_agent() -> Any:
    global _agent
    if _agent is None:
        async with _agent_lock:
            if _agent is None:
                try:
                    _agent = await create_support_agent()
                except RuntimeError as exc:
                    raise HTTPException(503, str(exc))
                except Exception as exc:  # RAG/MCP/network failures
                    raise HTTPException(503, f"Failed to initialise support agent: {exc}")
    return _agent


# How many durable messages are replayed into a fresh MemorySystem after a
# backend restart, so the agent regains conversational context (the UI already
# shows this history; without replay the agent would act amnesiac).
_REPLAY_LIMIT = 10


def session_state(session_id: str) -> dict[str, Any]:
    state = _session_states.get(session_id)
    if state is None:
        memory = MemorySystem()
        # Cold start (backend restarted): restore recent context from the
        # durable store so the conversation continues seamlessly.
        for msg in chat_store.history(session_id)[-_REPLAY_LIMIT:]:
            memory.remember(msg["role"], msg["content"], "anonymous")
        state = {"memory": memory, "active_user_id": "anonymous"}
        _session_states[session_id] = state
    return state


class SendIn(BaseModel):
    """Body for POST /chat/send."""
    message: str = Field(min_length=1)
    session_id: Optional[str] = None
    user_id: str = "anonymous"
    agent_id: Optional[str] = None  # support (default) | billing | dispatch


@router.post("/send")
async def send_message(body: SendIn):
    """Send one user message; returns the agent's reply (one full turn)."""
    session_id = body.session_id or f"chat-{uuid4().hex}"
    chat_store.ensure_session(session_id, body.user_id)

    # Agent switcher: billing -> SLA-dispute graph, dispatch ->
    # order-activation graph. Both run against the same shared database.
    agent_id = (body.agent_id or "support").strip().lower()
    if agent_id in {"billing", "dispatch"}:
        from backend.routes.chat_agents import run_billing_agent, run_dispatch_agent

        state = session_state(session_id)
        if agent_id == "billing":
            reply = run_billing_agent(session_id, body.message, state.get("active_user_id"))
        else:
            reply = run_dispatch_agent(session_id, body.message)
        chat_store.append(session_id, "user", body.message)
        chat_store.append(session_id, "assistant", reply)
        return {
            "session_id": session_id,
            "reply": reply,
            "agent": agent_id,
        }

    agent = await get_agent()

    state = session_state(session_id)
    memory: MemorySystem = state["memory"]
    active_user_id = state["active_user_id"]

    # Same loop body as planning_agent.run_agent's CLI, minus input()/print().
    memory.remember("user", body.message, active_user_id)
    memory.consolidation.run_if_due()

    verified_memory = memory.prompt_context(body.message, active_user_id)
    rolling_messages = [
        (item["role"], item["content"])
        for item in memory.short_term.context()
        if item["role"] in {"user", "assistant"}
    ]
    # Cap the window sent to the LLM: long conversations were pushing every
    # request past the provider's daily token budget (Groq free tier = 200k TPD).
    rolling_messages = rolling_messages[-6:]

    result = None
    pacer = get_pacer()
    for attempt in range(3):
        try:
            result = await agent.ainvoke(
                {"messages": [("system", verified_memory)] + rolling_messages},
                config={"callbacks": [pacer]} if pacer else None,
            )
            break
        except Exception as exc:
            detail = str(exc)
            rate_limited = (
                "rate_limit_exceeded" in detail
                or "Rate limit reached" in detail
                or "Rate limit exceeded" in detail  # OpenRouter wording
            )
            daily_cap = (
                "(TPD)" in detail
                or "tokens per day" in detail
                or "free-models-per-day" in detail
                or "free-models-per-day" in detail.lower()
            )
            # Transient upstream failures (provider overloaded, gateway 5xx).
            # These clear in seconds — retry quickly instead of failing the
            # user's turn.
            transient = (
                "temporarily overloaded" in detail.lower()
                or "upstream error" in detail.lower()
                or "'code': 502" in detail
                or "'code': 503" in detail
                or "code': 502" in detail
                or "code': 503" in detail
                or "bad gateway" in detail.lower()
                or "service unavailable" in detail.lower()
            )
            if transient and attempt < 2:
                await asyncio.sleep(3.0 * (attempt + 1))
                continue
            if not rate_limited:
                # Keep failures inside the CORS-wrapped response so the browser
                # receives clean JSON (an unhandled 500 loses CORS headers and
                # surfaces to users as a network error).
                raise HTTPException(502, f"Agent failed to respond: {exc}")
            if daily_cap:
                raise HTTPException(
                    429,
                    "Daily limit reached for this model. Try again later, "
                    "or switch OPENROUTER_MODEL/GROQ_MODEL in .env to another "
                    "model (each model has its own budget).",
                )
            # Per-minute (TPM) cap: agentic flows burst several large calls in
            # a row. Wait out the quoted window and retry transparently —
            # but only for short windows. A multi-minute quoted wait means
            # the daily/hourly budget is gone; sleeping would just hang UI.
            m = re.search(r"try again in ((\d+)m )?([\d.]+)s", detail)
            wait = 0.0
            if m:
                wait = float(m.group(3)) + (60 * int(m.group(2)) if m.group(2) else 0)
            if attempt == 2 or wait > 90:
                raise HTTPException(
                    429,
                    f"Rate limit reached for this model (retry in ~{int(wait)}s)."
                    if m else
                    "Daily limit reached for this model. Try again later, or "
                    "switch OPENROUTER_MODEL/GROQ_MODEL in .env to another model.",
                )
            await asyncio.sleep(min(wait + 2.0, 45))
    reply = result["messages"][-1].content

    for m in result["messages"]:
        for call in getattr(m, "tool_calls", None) or []:
            if call.get("name") == "verify_account_identity":
                account_id = call.get("args", {}).get("account_id")
                if account_id is not None:
                    state["active_user_id"] = str(account_id)

    memory.remember("assistant", reply, state["active_user_id"])

    chat_store.append(session_id, "user", body.message)
    chat_store.append(session_id, "assistant", reply)

    return {
        "session_id": session_id,
        "reply": reply,
        "active_account_id": state["active_user_id"],
    }


@router.get("/history/{session_id}")
def chat_history(session_id: str):
    """Retrieve the durable message history for one chat session."""
    if not chat_store.session_exists(session_id):
        raise HTTPException(404, f"unknown chat session: {session_id}")
    return {"session_id": session_id, "messages": chat_store.history(session_id)}


@router.get("/sessions")
def list_sessions():
    """Index of known chat sessions (newest first)."""
    return chat_store.sessions()
