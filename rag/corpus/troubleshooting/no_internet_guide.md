---
category: troubleshooting
model: all
doc_date: 2026-05-20
source_doc: no_internet_guide.md
---

# No Internet Service — Troubleshooting Guide

## 1. Step 1: Confirm Scope

Ask whether the outage affects one device or the whole home. Whole-home loss points to the modem/ONT, the fiber/coax drop, or the network. Single-device loss points to the device or Wi-Fi.

## 2. Step 2: Check the LED Panel

- **Optic-V1:** LOS solid red means the fiber link is lost; see ERR-5513 handling.
- **Coax-V2:** Online LED off or blinking means the modem is not registered with the CMTS; check for T3 timeouts (ERR-3321).
- **WiFi-V3:** WAN LED blinking amber means the router has no internet uplink; confirm the modem is online first.

## 3. Step 3: Remote Resync

Power-cycle the modem for 60 seconds (unplug, wait, replug). After reboot, allow 3-5 minutes for channel acquisition and registration. Run a network diagnostic sweep to check physical-layer health.

## 4. Step 4: Verify Account & Billing State

Confirm the account is not in an overdue balance state (ERR-6602) and that the plan is active. An account suspended for non-payment will present exactly like a total outage.

## 5. Step 5: Escalate Per Policy

If the sweep reports "FAIL - Modem unreachable" or optical power is below -27 dBm, follow the dispatch policy: inform the customer of the $150.00 truck-roll cost, confirm, and schedule with a verified session.

## 6. Storm-Specific Handling

During thunderstorms, expect coax T3 timeouts (ERR-3321) and fiber link flaps. If drops are intermittent rather than total, apply the DFS and signal-level checks before scheduling a dispatch.
