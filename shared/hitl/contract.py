from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class HumanDecision:
    status: str  # approved | rejected
    actor_id: str
    notes: str = ""

class HITLAdapter(Protocol):
    def create_request(self, run_id: str, payload: dict) -> str: ...
    def get_decision(self, request_id: str) -> HumanDecision | None: ...
