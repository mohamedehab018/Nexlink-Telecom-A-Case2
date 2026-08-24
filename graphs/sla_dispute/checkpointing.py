"""Dedicated LangGraph checkpoints for SLA disputes.

The project already owns a ``checkpoints`` table in its support database.  A
separate sidecar database prevents LangGraph's schema from colliding with it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from mcp_server.db import get_db_path


class SLACheckpointManager:
    def __init__(self) -> None:
        support_db = Path(get_db_path())
        self.db_path = str(support_db.with_name("sla_dispute_checkpoints.sqlite"))
        self._checkpointer_context = SqliteSaver.from_conn_string(self.db_path)
        self.checkpointer = self._checkpointer_context.__enter__()

    def get_checkpointer(self) -> SqliteSaver:
        return self.checkpointer

    def create_config(self, run_id: str) -> dict[str, Any]:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required.")
        return {"configurable": {"thread_id": run_id.strip()}}

    def get_latest_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        return self.checkpointer.get_tuple(self.create_config(run_id))

    def has_checkpoint(self, run_id: str) -> bool:
        return self.get_latest_checkpoint(run_id) is not None

    def get_checkpoint_state(self, run_id: str) -> Optional[dict[str, Any]]:
        checkpoint = self.get_latest_checkpoint(run_id)
        return None if checkpoint is None else checkpoint.checkpoint.get("channel_values", {})

    def clear_run(self, run_id: str) -> None:
        thread_id = self.create_config(run_id)["configurable"]["thread_id"]
        tables = {
            row[0]
            for row in self.checkpointer.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "checkpoint_writes" in tables:
            self.checkpointer.conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = ?", (thread_id,))
        if "checkpoints" in tables:
            self.checkpointer.conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        self.checkpointer.conn.commit()
