"""SQLite persistence, keeping an audit trail for every memory decision."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import MemoryItem, RoutingDecision, utcnow


class MemoryStore:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS routing_log (
          id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, user_id TEXT NOT NULL,
          item_json TEXT NOT NULL, destination TEXT NOT NULL, reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS episodes (
          id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL,
          summary TEXT NOT NULL, outcome TEXT, source_item_json TEXT NOT NULL,
          consolidated_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_episodes_user_time ON episodes(user_id, created_at);
        CREATE TABLE IF NOT EXISTS semantic_facts (
          fact_key TEXT PRIMARY KEY, user_id TEXT NOT NULL, value TEXT NOT NULL,
          status TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT, source_episode_id INTEGER);
        CREATE INDEX IF NOT EXISTS idx_semantic_user_status ON semantic_facts(user_id, status);
        CREATE TABLE IF NOT EXISTS semantic_versions (
          id INTEGER PRIMARY KEY, fact_key TEXT NOT NULL, value TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT,
          source_episode_id INTEGER, resolution TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS consolidation_runs (
          id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, notes TEXT NOT NULL);
        """)
        # Backward-compatible migration for databases created by the first
        # version of this module before explicit semantic version numbers.
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(semantic_versions)")}
        if "version" not in columns:
            self.conn.execute("ALTER TABLE semantic_versions ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def log_routing(self, item: MemoryItem, decision: RoutingDecision) -> None:
        self.conn.execute("INSERT INTO routing_log(created_at,user_id,item_json,destination,reason) VALUES(?,?,?,?,?)",
                          (utcnow(), item.user_id, json.dumps(item.as_dict()), decision.destination, decision.reason))
        self.conn.commit()

    def add_episode(self, item: MemoryItem, decision: RoutingDecision) -> int:
        cur = self.conn.execute("INSERT INTO episodes(user_id,created_at,summary,outcome,source_item_json) VALUES(?,?,?,?,?)",
            (item.user_id, item.created_at, decision.event_summary or item.content, decision.outcome, json.dumps(item.as_dict())))
        self.conn.commit()
        return int(cur.lastrowid)

    def unconsolidated_episodes(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM episodes WHERE consolidated_at IS NULL ORDER BY id").fetchall()

    def mark_consolidated(self, ids: Iterable[int], when: str) -> None:
        self.conn.executemany("UPDATE episodes SET consolidated_at=? WHERE id=?", [(when, i) for i in ids])
        self.conn.commit()

    def active_fact(self, fact_key: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM semantic_facts WHERE fact_key=?", (fact_key,)).fetchone()

    def upsert_fact(self, *, fact_key: str, user_id: str, value: str, source_episode_id: int,
                    now: str, expires_at: str | None, resolution: str) -> None:
        old = self.active_fact(fact_key)
        version_row = self.conn.execute("SELECT COALESCE(MAX(version), 0) FROM semantic_versions WHERE fact_key=?", (fact_key,)).fetchone()
        next_version = int(version_row[0]) + 1
        if old and old["value"] != value:
            self.conn.execute("UPDATE semantic_versions SET valid_to=?, status='superseded' WHERE fact_key=? AND valid_to IS NULL", (now, fact_key))
        self.conn.execute("INSERT INTO semantic_versions(fact_key,value,version,status,valid_from,source_episode_id,resolution) VALUES(?,?,?,?,?,?,?)",
            (fact_key, value, next_version, "active", now, source_episode_id, resolution))
        self.conn.execute("""INSERT INTO semantic_facts(fact_key,user_id,value,status,updated_at,expires_at,source_episode_id)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(fact_key) DO UPDATE SET value=excluded.value,status=excluded.status,
            updated_at=excluded.updated_at,expires_at=excluded.expires_at,source_episode_id=excluded.source_episode_id""",
            (fact_key, user_id, value, "active", now, expires_at, source_episode_id))
        self.conn.commit()

    def expire_facts(self, now: str) -> int:
        cur = self.conn.execute("UPDATE semantic_facts SET status='expired' WHERE status='active' AND expires_at IS NOT NULL AND expires_at<=?", (now,))
        self.conn.execute("""UPDATE semantic_versions SET status='expired', valid_to=?
            WHERE status='active' AND fact_key IN (
              SELECT fact_key FROM semantic_facts WHERE status='expired' AND expires_at IS NOT NULL AND expires_at<=?
            )""", (now, now))
        self.conn.commit(); return cur.rowcount

    def fact_rows(self, user_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM semantic_facts WHERE user_id=? AND status='active'", (user_id,)).fetchall()

    def fact_history(self, fact_key: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM semantic_versions WHERE fact_key=? ORDER BY version", (fact_key,)).fetchall()

    def search_episodes(self, user_id: str, query: str, limit: int = 5) -> list[sqlite3.Row]:
        """Retrieve candidate events before verification; this never returns them to the prompt by itself."""
        terms = [term for term in query.lower().split() if len(term) > 3]
        if not terms:
            return []
        clauses = " OR ".join("LOWER(summary) LIKE ?" for _ in terms)
        params = [user_id, *[f"%{term}%" for term in terms], limit]
        return self.conn.execute(f"SELECT * FROM episodes WHERE user_id=? AND ({clauses}) ORDER BY created_at DESC LIMIT ?", params).fetchall()

    def routing_log_rows(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT created_at, item_json, destination, reason FROM routing_log ORDER BY id").fetchall()

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO consolidation_runs(started_at,notes) VALUES(?,?)", (utcnow(), "periodic semantic consolidation"))
        self.conn.commit(); return int(cur.lastrowid)

    def finish_run(self, run_id: int, notes: str) -> None:
        self.conn.execute("UPDATE consolidation_runs SET completed_at=?,notes=? WHERE id=?", (utcnow(), notes, run_id)); self.conn.commit()

    def last_run_at(self) -> str | None:
        row = self.conn.execute("SELECT completed_at FROM consolidation_runs WHERE completed_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else None
