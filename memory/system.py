from __future__ import annotations

from pathlib import Path
from .consolidation import ConsolidationLayer
from .models import MemoryItem
from .router import PromoteOrDropRouter
from .short_term import ShortTermMemory
from .stores import MemoryStore
from .verification import verify_memory_recall


class MemorySystem:
    def __init__(self, db_path: str | Path = "db/nextlink.db", max_items: int = 20):
        self.store, self.router = MemoryStore(db_path), PromoteOrDropRouter()
        self.short_term = ShortTermMemory(max_items, self._handle_overflow)
        self.consolidation = ConsolidationLayer(self.store)

    def _handle_overflow(self, item: MemoryItem) -> None:
        decision = self.router.decide(item)
        self.store.log_routing(item, decision)
        if decision.destination == "episodic":
            self.store.add_episode(item, decision)

    def remember(self, role: str, content: str, user_id: str = "anonymous", **metadata) -> None:
        self.short_term.add(MemoryItem(role=role, content=content, user_id=user_id, metadata=metadata))

    def recall(self, query: str, user_id: str) -> list[str]:
        recalled = []
        for row in self.store.fact_rows(user_id):
            text = f"{row['fact_key']}: {row['value']}"
            check = verify_memory_recall(query, text)
            if check.passed: recalled.append(text)
        # Episodic candidates are also verified before they can be injected.
        for row in self.store.search_episodes(user_id, query):
            text = f"Episode {row['created_at']}: {row['summary']}"
            check = verify_memory_recall(query, text)
            if check.passed:
                recalled.append(text)
        return recalled

    def fact_history(self, fact_key: str) -> list[dict]:
        return [dict(row) for row in self.store.fact_history(fact_key)]

    def prompt_context(self, query: str, user_id: str) -> str:
        facts = self.recall(query, user_id)
        scratch = self.short_term.scratchpad
        return f"Scratchpad: {scratch}\nVerified long-term memories: {facts}"

    def close(self) -> None:
        self.store.close()
