from dataclasses import dataclass
from typing import Any, Optional, Protocol

DECISION_STATUSES = ('approved', 'rejected', 'modified')

@dataclass(frozen=True)
class HumanDecision:
    status: str  # approved | rejected | modified
    actor_id: str
    notes: str = ""
    # Required when status == "modified": edits merged into the original payload.
    modified_payload: Optional[dict[str, Any]] = None

class HITLAdapter(Protocol):
    def create_request(self, run_id: str, payload: dict) -> str: ...
    def get_decision(self, request_id: str) -> HumanDecision | None: ...
