---
category: policy
model: all
doc_date: 2026-03-02
source_doc: service_credit_policy.md
---

# Nextlink Residential ISP — Service Credit & Billing Adjustment Policy

## 1. Overview

This policy governs the issuance of monetary billing credits to customer accounts by support personnel. All credits must correspond to an active or recent support ticket and serve a documented business purpose.

## 2. Eligible Circumstances

Billing credits are justified under the following specific conditions:

- **Service Outages:** Verified outages lasting longer than 4 consecutive hours (pro-rated daily credit).
- **Equipment Degradation:** Chronic physical medium or hardware faults resulting in severe impairment (more than 24 hours).
- **Billing Errors:** Incorrect tier charges or double-billing occurrences.
- **Missed Technician Appointments:** Nextlink missed a scheduled technician dispatch window ($20 appointment guarantee credit).

## 3. Authorization Thresholds & Governance

### 3.1 Standard Agent Threshold (≤ $25.00)

Front-line support agents may issue up to $25.00 per incident independently, provided customer identity verification (`verify_account_identity`) has succeeded.

### 3.2 Elevated Credit Threshold (> $25.00)

Any single credit exceeding $25.00 requires explicit real-time Supervisor sign-off (elicitation confirmation). Supervisors may approve credits up to the absolute maximum without further escalation.

### 3.3 Absolute Maximum Single Credit ($500.00)

No single credit transaction may exceed $500.00 under any circumstances. The system rejects any credit request above this hard cap automatically. If the billing system receives a credit request above the $500.00 hard cap, the request fails with error code **ERR-4091** ("CREDIT_LIMIT_EXCEEDED") and the transaction is not applied.

## 4. Record Keeping

All approved credits must append an audit note to the associated support ticket detailing the credit amount and justification. The audit note must include the ticket ID, the amount, and the approver (agent or supervisor ID).

## 5. Stale Ticket Rule

Credits may only be applied to tickets that are open or were closed within the last 30 days. Credits attempted against tickets closed more than 30 days ago are rejected with **ERR-4091** as well, because the ticket is no longer actionable.

## 6. Downgrade Protection

Accounts that have been a customer for more than 12 consecutive months receive downgrade protection: any plan change is processed immediately with no re-provisioning fee. Account changes attempted on accounts in arrears are blocked with error **ERR-6602** ("OVERDUE_BALANCE") until the balance is settled.
