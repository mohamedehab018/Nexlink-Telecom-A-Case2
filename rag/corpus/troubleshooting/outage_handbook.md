---
category: troubleshooting
model: all
doc_date: 2026-02-10
source_doc: outage_handbook.md
---

# Outage Handling Handbook

## 1. Outage Definition

An outage is a verified loss of service affecting one or more customers. A single-account outage is handled as a ticket; a regional outage is escalated to the network operations center.

## 2. Verifying an Outage

Confirm the outage with a network diagnostic sweep and by checking the customer's equipment logs:

- **Optic-V1:** ERR-5513 (OPTIC_LINK_DOWN) confirms fiber link loss.
- **Coax-V2:** ERR-3321 (COAX_T3_TIMEOUT) confirms upstream channel loss.
- Check the account billing state for ERR-6602 (OVERDUE_BALANCE), which looks identical to an outage.

## 3. Outage Credit Eligibility

Per the service credit policy, customers are eligible for a pro-rated credit when a verified outage lasts longer than **4 consecutive hours**. Compute the pro-rated credit from the customer's monthly plan cost divided by the days in the billing month, multiplied by the full outage days.

### Example

A Premium customer ($60.00/mo) on a 30-day billing cycle with a verified 2-day outage qualifies for a pro-rated credit of $60.00 / 30 * 2 = $4.00. A 6-hour outage (0.25 days) yields $0.50 — well under the $25.00 standard agent threshold, so no supervisor approval is needed.

## 4. Chronic Degradation Credit

When a hardware fault (optical power below -27 dBm, recurring T3 timeouts) impairs service for more than 24 hours, the account is eligible for a credit under equipment degradation. If the credit exceeds $25.00, supervisor sign-off is required (Section 3.2 of the credit policy); anything above $500.00 is blocked with ERR-4091.

## 5. Communicating with the Customer

Draft the outage explanation using the account details, ticket history, and equipment diagnostics. Explain the cause in plain language, state the current status, and outline next steps (remote resync, dispatch, or credit application).

## 6. Documentation

Every outage must end with a support ticket that records the cause, the verification method, and any credit applied.
