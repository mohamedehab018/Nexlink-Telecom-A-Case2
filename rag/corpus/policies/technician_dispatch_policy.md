---
category: policy
model: all
doc_date: 2026-02-18
source_doc: technician_dispatch_policy.md
---

# Nextlink Technician Dispatch Policy

## 1. When a Dispatch Is Required

A technician dispatch is the escalation path used when a problem cannot be resolved remotely. Dispatches are required when:

- The physical line (fiber, coax, or copper drop) is damaged or severed.
- The modem or ONT is reporting a hardware fault that a remote reboot cannot clear.
- The network diagnostic sweep reports a physical-layer failure (e.g., "FAIL - Modem unreachable").
- Optical power on a fiber ONT drops below -27 dBm and a remote resync does not restore service.

## 2. Dispatch Cost & Customer Notification

Every scheduled dispatch incurs a **$150.00 truck-roll cost** that is applied to the customer's next bill unless the failure is caused by Nextlink equipment. Support agents MUST inform the customer of this cost before scheduling.

## 3. Dispatch Confirmation Flow

1. Agent explains the $150.00 truck-roll cost.
2. Agent schedules the dispatch, which triggers a client-side confirmation elicitation.
3. The customer confirms the visit window and provides access instructions.
4. The dispatch ticket is created with status "open" and ticket type "dispatch".

## 4. Service Guarantee Credit

If Nextlink misses a scheduled dispatch window, the customer is entitled to a **$20.00 appointment guarantee credit**, applied per the service credit policy. This credit does not require supervisor approval.

## 5. Same-Day Dispatch Eligibility

Dispatch requests received before 2:00 PM local time are eligible for same-day scheduling when a technician is available in the customer's service zone. Requests after 2:00 PM are scheduled for the next business day.

## 6. Unverified Session Block

Dispatch scheduling is a write action and therefore requires a verified account session. If no PIN verification has succeeded in the current session, the dispatch request is blocked with error **ERR-9910** ("DISPATCH_BLOCKED") and the agent must prompt the customer for their 4-digit security PIN before proceeding.
