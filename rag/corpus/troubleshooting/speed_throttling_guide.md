---
category: troubleshooting
model: all
doc_date: 2026-04-25
source_doc: speed_throttling_guide.md
---

# Slow Speeds & Throttling — Troubleshooting Guide

## 1. Symptom Classification

Ask whether slow speeds appear on Wi-Fi, Ethernet, or the whole connection. Test with a wired client to separate Wi-Fi interference from upstream congestion.

## 2. Wi-Fi Speed Checks

- Confirm the client is connected to a 5 GHz band, not 2.4 GHz.
- Check the WiFi-V3 router for DFS-channel activity (ERR-7745) that can cause repeated drops.
- Place the client within range; walls and metal reduce throughput substantially.
- Check for co-channel interference from neighbor networks on 2.4 GHz.

## 3. Modem Signal Checks

- **Coax-V2:** Downstream SNR below 28 dB or upstream SNR below 30 dB is degraded; check connectors and moisture (see ERR-3321).
- **Optic-V1:** Optical power below -27 dBm is degraded; reseat the fiber and resync (see ERR-5513).

## 4. Plan vs. Actual Throughput

Customers should expect roughly 85-90% of the plan's max speed over a wired connection. The plans are:

- **Basic:** $20.00/mo, 30 Mbps
- **Standard:** $35.00/mo, 50 Mbps
- **Premium:** $60.00/mo, 100 Mbps

The Premium plan is the most expensive and the fastest residential tier.

Test against the provisioned tier before assuming throttling. If a wired client saturates the plan, the bottleneck is Wi-Fi or the device, not the network.

## 5. Throttling & Data Policy

Nextlink does not impose data caps on residential plans, so customers cannot be "throttled" for usage. If speeds degrade consistently during peak hours (7-11 PM), advise a plan upgrade rather than a ticket.

## 6. Document the Diagnosis

Always log a support ticket with the measured speeds and the checks performed so repeat reports are easy to compare.
