"""Periodic episodic-to-semantic consolidation, including conflict and expiry handling."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .stores import MemoryStore


class ConsolidationLayer:
    def __init__(self, store: MemoryStore, interval: timedelta = timedelta(minutes=15), ttl_days: int = 90):
        self.store, self.interval, self.ttl_days = store, interval, ttl_days

    def run_if_due(self, now: datetime | None = None, force: bool = False) -> dict:
        now = now or datetime.now(timezone.utc)
        last = self.store.last_run_at()
        if not force and last and now - datetime.fromisoformat(last) < self.interval:
            return {"ran": False, "reason": "not due"}
        run_id, processed, updates, conflicts = self.store.start_run(), [], 0, []
        for episode in self.store.unconsolidated_episodes():
            candidate = self._extract_candidate(episode["summary"], episode["user_id"])
            processed.append(episode["id"])
            if not candidate:
                continue
            key, value = candidate
            old = self.store.active_fact(key)
            resolution = "new fact"
            if old and old["value"].lower() != value.lower():
                # Newer timestamped episode wins; old value remains queryable in semantic_versions.
                resolution = f"conflict resolved: newer episode replaces '{old['value']}'"
                conflicts.append({"key": key, "old": old["value"], "new": value})
            if not old or old["value"].lower() != value.lower():
                self.store.upsert_fact(fact_key=key, user_id=episode["user_id"], value=value,
                    source_episode_id=episode["id"], now=now.isoformat(),
                    expires_at=(now + timedelta(days=self.ttl_days)).isoformat(), resolution=resolution)
                updates += 1
        self.store.mark_consolidated(processed, now.isoformat())
        expired = self.store.expire_facts(now.isoformat())
        self.store.finish_run(run_id, f"episodes={len(processed)}, updates={updates}, conflicts={len(conflicts)}, expired={expired}")
        return {"ran": True, "episodes": len(processed), "updates": updates, "conflicts": conflicts, "expired": expired}

    @staticmethod
    def _extract_candidate(text: str, user_id: str) -> tuple[str, str] | None:
        # Evidence remains in episodic memory; this extraction only happens during the periodic pass.
        match = re.search(r"(?:preferred contact method|contact preference)\s+(?:is|to|changed?\s+to|updated?\s+to|from\s+\w+\s+to)\s+(email|sms|phone)", text, re.I)
        if not match:
            return None
        return f"{user_id}:contact_preference", match.group(1).lower()
