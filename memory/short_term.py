"""Rolling working memory and a distinct scratchpad."""
from __future__ import annotations

from collections import deque
from .models import MemoryItem


class ShortTermMemory:
    def __init__(self, max_items: int, on_evict):
        self.max_items, self.on_evict = max_items, on_evict
        self.messages: deque[MemoryItem] = deque()
        self.scratchpad: dict[str, str] = {"plan": "", "current_subgoal": "", "working_state": ""}

    def add(self, item: MemoryItem) -> None:
        self.messages.append(item)
        while len(self.messages) > self.max_items:
            self.on_evict(self.messages.popleft())

    def set_working_state(self, *, plan: str | None = None, current_subgoal: str | None = None, working_state: str | None = None) -> None:
        for key, value in {"plan": plan, "current_subgoal": current_subgoal, "working_state": working_state}.items():
            if value is not None: self.scratchpad[key] = value

    def context(self) -> list[dict]:
        return [item.as_dict() for item in self.messages]
