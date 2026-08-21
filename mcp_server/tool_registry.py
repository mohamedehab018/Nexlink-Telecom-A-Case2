"""Persisted per-agent MCP capability registry; safe for admin API callers."""
from __future__ import annotations
import sqlite3
from typing import Any
from .db import get_db_path

def _conn():
    c = sqlite3.connect(get_db_path()); c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS agent_tools (
      agent_id TEXT NOT NULL, tool_name TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
      tool_spec_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(agent_id, tool_name))""")
    return c

def register_tool(agent_id: str, tool_spec: dict[str, Any]) -> None:
    name = tool_spec.get('name')
    if not isinstance(agent_id, str) or not agent_id or not isinstance(name, str) or not name:
        raise ValueError('agent_id and tool_spec.name are required')
    import json
    c = _conn()
    try: c.execute("INSERT INTO agent_tools VALUES(?,?,1,?) ON CONFLICT(agent_id,tool_name) DO UPDATE SET enabled=1,tool_spec_json=excluded.tool_spec_json", (agent_id, name, json.dumps(tool_spec))); c.commit()
    finally: c.close()

def deregister_tool(agent_id: str, tool_name: str) -> None:
    c = _conn()
    try: c.execute("UPDATE agent_tools SET enabled=0 WHERE agent_id=? AND tool_name=?", (agent_id, tool_name)); c.commit()
    finally: c.close()

def enabled_tools(agent_id: str, available: list[dict[str, Any]]) -> list[dict[str, Any]]:
    c = _conn()
    try: rows = c.execute("SELECT tool_name FROM agent_tools WHERE agent_id=? AND enabled=1", (agent_id,)).fetchall()
    finally: c.close()
    enabled = {r['tool_name'] for r in rows}
    return [spec for spec in available if spec.get('name') in enabled]
