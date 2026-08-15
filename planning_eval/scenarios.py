"""Real, recurring support-staff requests used to exercise the planning agent.

These are the "genuine planning problem" for Nexlink: a staff request that
bundles ambiguous sub-issues for one account and ends in a high-stakes write
(technician dispatch ~$150, billing credit with a >$25 supervisor gate, or a
ticket). The right resolution depends on intermediate observations, and every
write is gated by a session-verification step that is invisible at plan time
-- which is exactly why decomposition-first and dynamic decomposition diverge.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

# ---------------------------------------------------------------------------
# The real request type: "resolve this incident bundle".
# Each bundle needs reads (account, equipment, tickets), a judgement about the
# right resolution (dispatch vs remote fix vs credit), and an authenticated
# write. A wrong plan has a real cost: an unnecessary $150 truck-roll, or a
# credit applied without authorization.
# ---------------------------------------------------------------------------

OUTAGE_BUNDLE_WALTER_WHITE: Dict = {
    "id": "outage-bundle-walter-white",
    "account_id": 2,
    "pin": 5678,
    "staff_request": (
        "Walter White at 308 Negra Arroyo Lane is reporting total internet "
        "loss since this morning. His modem status looks fine on our side "
        "but he's demanding someone comes out today. Resolve the incident."
    ),
    "expected_resolution": "no_dispatch_required",  # diagnostics say SYS_OK
}

FAULTY_MODEM_BUNDLE_ELLEN_RIPLEY: Dict = {
    "id": "faulty-modem-bundle-ellen-ripley",
    "account_id": 3,
    "pin": 9999,
    "staff_request": (
        "Ellen Ripley (account 3) has a solid red LED on the Coax-V2 and "
        "drops every thunderstorm. Equipment log shows a hardware fault. "
        "She wants a technician out this week. Resolve the incident."
    ),
    "expected_resolution": "dispatch_required",  # HW_FAULT / physical line
}

BILLING_BUNDLE_SARAH_BRANDEN: Dict = {
    "id": "billing-bundle-sarah-branden",
    "account_id": 1,
    "pin": 1234,
    "staff_request": (
        "Sarah Branden (account 1) was double-billed last month. She called "
        "and we promised a $30 credit on her open billing ticket. Please "
        "resolve it."
    ),
    "expected_resolution": "credit_applied",
}


def credential_provider_for(scenario: Dict) -> Callable[[int], Optional[int]]:
    """Stand-in for the support staff typing their 4-digit PIN when the agent
    has to verify an unverified session mid-plan."""
    pin = scenario.get("pin")

    def provider(account_id: int) -> Optional[int]:
        if int(scenario.get("account_id")) == int(account_id):
            return pin
        return None

    return provider
