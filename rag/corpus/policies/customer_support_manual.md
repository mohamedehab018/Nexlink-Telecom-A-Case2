---
category: policy
model: all
doc_date: 2026-01-30
source_doc: customer_support_manual.md
---

# Nextlink Customer Support Manual

## 1. Identity Verification Standard

Support agents MUST verify a customer's identity using the 4-digit security PIN before performing any write action (creating tickets, scheduling dispatches, or applying credits). Verification failures are limited to three attempts. After the third consecutive failed attempt, the account is locked from remote operations for 30 minutes and any further attempt returns error **ERR-2210** ("AUTH_FAILED").

## 2. Account Lookup

Customers may be located by full name, partial name, or account ID. Agents should confirm the account address with the customer before proceeding with any sensitive action. Security PINs are never displayed in tool responses.

## 3. Routine Inbound Flow

1. Greet the customer and confirm identity (name and address).
2. Look up the account and summarize the current plan.
3. Diagnose the reported issue using equipment logs and network sweeps.
4. Resolve remotely when possible; escalate to dispatch only when required by policy.
5. Log a support ticket for every resolved or escalated incident.

## 4. Response Time Targets

- **Critical outage** (whole-home loss of service): first response within 15 minutes.
- **Degraded service** (slow speeds, intermittent drops): first response within 1 hour.
- **Billing inquiry**: first response within 4 business hours.

## 5. Plan Change Rules

Customers on any plan may upgrade immediately. Downgrades are processed at the next billing cycle start. Accounts with an overdue balance are blocked from plan changes with error **ERR-6602** ("OVERDUE_BALANCE"). Accounts in good standing for more than 12 months receive downgrade protection per the service credit policy.

## 6. Credit Policy Reference

Agents should consult the Service Credit Policy for thresholds. Standard agents may issue up to $25.00 independently; anything above that requires supervisor sign-off, and nothing above the $500.00 hard cap may ever be issued (error **ERR-4091**).
