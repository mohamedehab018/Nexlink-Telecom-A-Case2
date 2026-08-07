---
category: troubleshooting
model: all
doc_date: 2026-06-15
source_doc: wifi_optimization_guide.md
---

# Wi-Fi Optimization Guide

## 1. Channel Selection

For the WiFi-V3 router, prefer **non-DFS 5 GHz channels (36-48, 149-165)** to avoid the radar-induced dropouts logged as ERR-7745. On 2.4 GHz, choose channels 1, 6, or 11 and check for neighbor overlap.

## 2. Band Steering

Band steering moves clients to the best available radio automatically. If a device keeps dropping, disable band steering and assign the device to a dedicated 5 GHz SSID instead.

## 3. Placement

- Central location, elevated, away from metal objects and fish tanks.
- Keep the router at least 1 m from microwave ovens and cordless phones.
- Do not place the router inside cabinets or behind televisions.

## 4. Guest Network

Enable guest network isolation for visitor devices so they cannot reach the customer's IoT band. The IoT band is isolated by default on the WiFi-V3.

## 5. Mesh Nodes

Add mesh nodes to extend coverage to dead zones. Each node links to the primary router; confirm the Mesh LED is solid blue after pairing. Nodes should be within 10 m of the previous node for a stable link.

## 6. When to Reboot

Reboot the router only when the WAN LED is solid green; never power-cycle during the 3:00-5:00 AM firmware window.
