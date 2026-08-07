from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryItem:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    user_id: str
    created_at: str = field(default_factory=utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoutingDecision:
    destination: Literal["forget", "episodic"]
    reason: str
    event_summary: str | None = None
    outcome: str | None = None


@dataclass
class VerificationResult:
    passed: bool
    reason: str
    score: float
