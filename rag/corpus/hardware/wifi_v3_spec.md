---
category: hardware
model: Nextlink-WiFi-V3
doc_date: 2026-05-05
source_doc: wifi_v3_spec.md
---

# Nextlink-WiFi-V3 Router — Hardware Specification

## 1. Overview

The Nextlink-WiFi-V3 is a tri-band Wi-Fi 6 router used as the customer-premises router behind the Nextlink-Optic-V1 or Nextlink-Coax-V2 modem. It provides one SSID with band steering plus a dedicated IoT band.

## 2. Physical Specifications

- **Radio:** Wi-Fi 6 (802.11ax), 2.4 GHz + 2x 5 GHz.
- **Ethernet:** 1x 2.5G WAN, 4x Gigabit LAN.
- **Mesh:** Supports up to 3 nodes in a Nextlink Mesh.
- **Power:** 12V DC, 2.5A adapter.
- **Security:** WPA3, Guest network isolation.

## 3. LED Reference

| LED | State | Meaning |
| --- | --- | --- |
| Power | Solid white | Unit healthy |
| WAN | Solid green | Internet uplink active |
| WAN | Blinking amber | No WAN connection; check modem |
| Mesh | Solid blue | Mesh node linked to primary |
| IoT | Solid green | IoT band active |

## 4. DFS Channel Behavior — ERR-7745

By default the 5 GHz radios use DFS (Dynamic Frequency Selection) channels to share spectrum with radar systems. When radar is detected, the router is forced to vacate the DFS channel, which causes a brief service drop while it re-scans. If the router is near radar interference (airports, weather stations), the repeated vacate/re-scan cycles produce dropouts and the router logs **ERR-7745** ("WIFI_DFS").

### Remedy for ERR-7745

1. In the router config, move the 5 GHz radio from DFS channels (52-144) to a non-DFS channel (36-48, 149-165).
2. Disable "Auto-DFS" if the option is available.
3. If dropouts persist, separate the SSIDs into distinct 5 GHz channels for the two radios instead of using band steering.
4. Log a support ticket documenting the change so recurring ERR-7745 entries are tracked.

## 5. Firmware

Firmware updates are pushed automatically between 3:00 AM and 5:00 AM local time. Rebooting the router mid-update can corrupt the image; always confirm the WAN LED is solid green before power-cycling.
