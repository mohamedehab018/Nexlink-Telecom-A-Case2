---
category: hardware
model: Nextlink-Coax-V2
doc_date: 2026-03-22
source_doc: coax_v2_spec.md
---

# Nextlink-Coax-V2 Cable Modem — Hardware Specification

## 1. Overview

The Nextlink-Coax-V2 is a DOCSIS 3.1 cable modem for Nextlink's hybrid fiber-coax network. It supports high-split spectrum and is the standard unit deployed on coax drops.

## 2. Physical Specifications

- **Uplink:** DOCSIS 3.1 over coax (F-type connector, 75 ohm).
- **LAN Ports:** 2x Gigabit Ethernet (RJ-45).
- **USB:** 1x USB 2.0 (diagnostics only).
- **Power:** 12V DC, 2A adapter.
- **Bonded Channels:** 32x8 (32 downstream, 8 upstream).

## 3. LED Reference

| LED | State | Meaning |
| --- | --- | --- |
| Power | Solid green | Powered and healthy |
| DS | Solid green | Downstream channels locked |
| US | Solid green | Upstream channels locked |
| DS / US | Blinking | Channel acquisition in progress |
| Online | Solid green | Modem fully registered and online |
| Online | Solid red | Modem online but degraded signal quality |
| Online | Off | Not registered with the CMTS |

## 4. Signal Quality Thresholds

- **Downstream SNR:** healthy above 30 dB; below 28 dB is degraded.
- **Upstream SNR:** healthy above 33 dB; below 30 dB is degraded.
- **Receive level:** -10 dBmV to +10 dBmV is healthy.

## 5. T3 Timeout — ERR-3321

During storms or when the upstream path is noisy, the modem may fail to receive a range request response from the CMTS, producing a **T3 timeout** and logging **ERR-3321** ("COAX_T3_TIMEOUT"). The modem loses upstream channel lock and the Online LED blinks or drops.

### Remedy for ERR-3321

1. Verify the coax connector is finger-tight and free of corrosion.
2. Check for moisture in the cable entry point; replace the connector if corroded.
3. Power-cycle the modem for 60 seconds to force a fresh upstream range request.
4. If ERR-3321 recurs after two power cycles, the physical drop is suspect — schedule a technician dispatch, because the customer also typically reports intermittent drops during weather events.

## 6. Placement Notes

Keep the modem out of enclosed cabinets to avoid overheating. Coax should not share a path with power lines.
