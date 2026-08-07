---
category: troubleshooting
model: all
doc_date: 2026-06-01
source_doc: error_code_reference.md
---

# Nextlink Error Code Reference

This catalog is the canonical reference for hardware and billing error codes. Agents should use the exact code string when searching.

## ERR-4091 — CREDIT_LIMIT_EXCEEDED

- **Meaning:** A billing credit request exceeded the $500.00 hard cap, or targeted a ticket closed more than 30 days ago.
- **Context:** Service credit policy, Section 3.3 and Section 5.
- **Remedy:** Recalculate the credit amount below $500.00 and confirm the ticket is open or closed within the last 30 days. If the amount is above $25.00, obtain supervisor sign-off.

## ERR-2210 — AUTH_FAILED

- **Meaning:** Three consecutive failed PIN verification attempts on an account.
- **Context:** Customer Support Manual, Section 1.
- **Remedy:** The account is locked from remote write operations for 30 minutes. Advise the customer to wait, or escalate to a manager to unlock the account. Do NOT keep retrying.

## ERR-5513 — OPTIC_LINK_DOWN

- **Meaning:** Fiber optical link loss on a Nextlink-Optic-V1 ONT; optical power below -27 dBm or LOS triggered.
- **Context:** Optic-V1 hardware spec, Section 4.
- **Remedy:** Reseat the fiber connector, check the drop for damage, perform a remote resync, and escalate to dispatch if optical power remains below -27 dBm.

## ERR-3321 — COAX_T3_TIMEOUT

- **Meaning:** A Nextlink-Coax-V2 cable modem lost upstream channel lock due to a T3 timeout.
- **Context:** Coax-V2 hardware spec, Section 5.
- **Remedy:** Tighten/replace the coax connector, check for moisture, power-cycle for 60 seconds, and dispatch if the error recurs — customers commonly report intermittent drops during storms.

## ERR-7745 — WIFI_DFS

- **Meaning:** A Nextlink-WiFi-V3 router vacated a DFS 5 GHz channel due to radar detection, causing dropouts.
- **Context:** WiFi-V3 hardware spec, Section 4.
- **Remedy:** Move the 5 GHz radio to a non-DFS channel (36-48 or 149-165), disable auto-DFS, and split the SSIDs if dropouts persist.

## ERR-9910 — DISPATCH_BLOCKED

- **Meaning:** A dispatch scheduling attempt was blocked because the session is not PIN-verified.
- **Context:** Technician Dispatch Policy, Section 6.
- **Remedy:** Prompt the customer for their 4-digit security PIN and verify before retrying.

## ERR-6602 — OVERDUE_BALANCE

- **Meaning:** A plan change or service action was blocked because the account has an overdue balance.
- **Context:** Customer Support Manual, Section 5; Service Credit Policy, Section 6.
- **Remedy:** Instruct the customer to settle the balance, then retry the action once the account is current.
