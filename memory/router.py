"""The promote-or-drop boundary. It deliberately never writes semantic memory."""
from __future__ import annotations

import re

from .models import MemoryItem, RoutingDecision


class PromoteOrDropRouter:
    """A deterministic, inspectable router suitable for a support workflow.

    Production teams can replace ``decide`` with a structured LLM call, but the
    returned decision must remain one of only ``forget`` or ``episodic``.
    """

    EPISODIC_PATTERNS = (
        r"\b(prefer|preference|contact method|call me|email me|sms|text me)\b",
        r"\b(updated?|changed?|moved?|cancelled?|requested?|reported?|confirmed?)\b",
        r"\b(ticket|dispatch|appointment|outage|technician|credit|incident)\b",
        r"\b(account\s*#?\d+|customer\s*#?\d+)\b",
    )

    def decide(self, item: MemoryItem) -> RoutingDecision:
        text = item.content.strip()
        if item.role == "tool" or not text:
            return RoutingDecision("forget", "Tool output/empty content is transient and is not an event.")
        if len(text) < 12 or re.search(r"\b(thanks|hello|okay|got it)\b", text, re.I):
            return RoutingDecision("forget", "Small talk or acknowledgement has no durable support value.")
        if any(re.search(pattern, text, re.I) for pattern in self.EPISODIC_PATTERNS):
            return RoutingDecision(
                "episodic",
                "Contains a customer-specific support event, preference, or outcome that may matter later.",
                event_summary=text,
                outcome=item.metadata.get("outcome"),
            )
        return RoutingDecision("forget", "No durable customer event or reusable evidence was found.")
