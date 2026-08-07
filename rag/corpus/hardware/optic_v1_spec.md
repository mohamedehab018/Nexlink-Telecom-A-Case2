---
category: hardware
model: Nextlink-Optic-V1
doc_date: 2026-04-10
source_doc: optic_v1_spec.md
---

# Nextlink-Optic-V1 ONT / Modem — Hardware Specification

## 1. Overview

The Nextlink-Optic-V1 is a fiber-to-the-home optical network terminal (ONT). It provides a GPON uplink to the Nextlink fiber network and delivers internet service over Ethernet and Wi-Fi.

## 2. Physical Specifications

- **Uplink:** GPON, single SC/APC fiber connector.
- **LAN Ports:** 4x Gigabit Ethernet (RJ-45).
- **Wi-Fi:** 802.11ac dual-band (2.4 GHz / 5 GHz), 4x4 MIMO.
- **Power:** 12V DC, 1.5A adapter.
- **Operating Range:** -10°C to 45°C.

## 3. LED Reference

| LED | State | Meaning |
| --- | --- | --- |
| Power | Solid green | Unit powered and healthy |
| Power | Off | No power; check adapter and outlet |
| PON | Solid green | Fiber link established |
| PON | Blinking | Attempting to register with the OLT |
| LOS | Solid red | Optical signal lost; fiber issue |
| LAN | Solid green | Ethernet link active |
| LAN | Blinking | Data transfer in progress |
| Wi-Fi | Solid blue | Wi-Fi radios on and broadcasting |
| Wi-Fi | Off | Wi-Fi radios disabled |

## 4. Optical Power Monitoring

Healthy optical receive power is between **-8 dBm and -27 dBm**. When the ONT reports optical power below -27 dBm, the unit emits a **WARN** entry and the LOS LED may illuminate. When the link is fully lost, the ONT logs **ERR-5513** ("OPTIC_LINK_DOWN").

### Remedy for ERR-5513

1. Reseat the SC/APC fiber connector on both ends.
2. Check the fiber drop for sharp bends, cuts, or water ingress.
3. Perform a remote resync (reboot the ONT via the network operations tool).
4. If optical power is still below -27 dBm after resync, escalate to a technician dispatch, since a physical fiber fault is indicated.

## 5. Recommended Placement

Install the ONT away from direct sunlight, near the power outlet, with the fiber drop protected from foot traffic. Avoid coiling the fiber tightly (bend radius should stay above 30 mm).
