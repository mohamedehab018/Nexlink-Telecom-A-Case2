"""Atomic SQLite checkpoints shared by all Nexlink state graphs.

Payload is intentionally opaque JSON: graph-specific fields belong to the caller.
The ``completed_effects`` map provides an idempotency ledger across process restarts.
"""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA_VERSION = 1

class CheckpointStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        conn = self._connect()
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS graph_checkpoints (
              checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
              graph_name TEXT NOT NULL, version INTEGER NOT NULL, state_json TEXT NOT NULL,
              created_at TEXT NOT NULL, UNIQUE(run_id, checkpoint_id))""")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_graph_checkpoints_run ON graph_checkpoints(run_id, checkpoint_id DESC)")
            conn.commit()
        finally:
            conn.close()

    def save(self, run_id: str, graph_name: str, state: Mapping[str, Any], version: int = SCHEMA_VERSION) -> int:
        # json serialization happens before opening the transaction; malformed state cannot leave a partial row.
        payload = json.dumps(dict(state), sort_keys=True, default=str)
        conn = self._connect()
        try:
            row = conn.execute("INSERT INTO graph_checkpoints(run_id,graph_name,version,state_json,created_at) VALUES(?,?,?,?,?)",
                (run_id, graph_name, version, payload, datetime.now(timezone.utc).isoformat())).lastrowid
            conn.commit()
        finally:
            conn.close()
        return int(row)

    def load_latest(self, run_id: str, compatible_versions: set[int] | None = None) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM graph_checkpoints WHERE run_id=? ORDER BY checkpoint_id DESC", (run_id,)).fetchall()
        finally:
            conn.close()
        allowed = compatible_versions or {SCHEMA_VERSION}
        for row in rows:  # skip a corrupt newest row, retaining the last valid resume point
            if row['version'] not in allowed: continue
            try:
                state = json.loads(row['state_json'])
                if not isinstance(state, dict): raise ValueError('state is not an object')
                state['checkpoint_id'] = row['checkpoint_id']
                return state
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        return None

    def history(self, run_id: str) -> list[dict[str, Any]]:
        """Inspectable, durable checkpoint metadata for platform/admin recovery."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT checkpoint_id,graph_name,version,state_json,created_at FROM graph_checkpoints WHERE run_id=? ORDER BY checkpoint_id DESC", (run_id,)).fetchall()
            return [{**dict(row), "state": json.loads(row["state_json"])} for row in rows]
        finally:
            conn.close()

def save_checkpoint(store: CheckpointStore, run_id: str, graph_name: str, state: Mapping[str, Any]) -> int:
    return store.save(run_id, graph_name, state)

def load_checkpoint(store: CheckpointStore, run_id: str) -> dict[str, Any] | None:
    return store.load_latest(run_id)

def resume_run(store: CheckpointStore, run_id: str, runner: Callable[[dict[str, Any]], Any]) -> Any:
    state = load_checkpoint(store, run_id)
    if state is None: raise LookupError(f"No valid checkpoint for run {run_id}")
    return runner(state)
