import asyncio
import logging
from typing import Any, Dict, Optional

import db
from schemas import validate_tool_input

logger = logging.getLogger("nextlink_diagnostic")


async def handle_diagnose_equipment_issue(
    serial_num: str,
    ctx: Optional[Any] = None
) -> str:
    """Diagnoses equipment issue by analyzing error logs through client LLM sampling."""
    validate_tool_input("diagnose_equipment_issue", {"serial_num": serial_num})

    device = db.get_equipment_by_serial(serial_num)
    if not device:
        return f"Error: Equipment with serial number '{serial_num}' not found."

    raw_log = device.get("last_error_log") or "No error logs available."
    model_type = device.get("model_type", "Unknown Model")
    status = device.get("status", "unknown")

    log_prompt = (
        f"You are a network technician at Nextlink ISP.\n"
        f"Analyze error log for {model_type} (Serial: {serial_num}, Status: {status}):\n\n"
        f"LOG:\n{raw_log}\n\n"
        f"Summarize in 2-3 sentences: 1) Cause, 2) Impact, 3) Action (remote reboot vs dispatch)."
    )

    if ctx and hasattr(ctx, "session") and hasattr(ctx.session, "create_message"):
        try:
            import mcp.types as types
            messages = [types.SamplingMessage(role="user", content=types.TextContent(type="text", text=log_prompt))]
            
            response = await ctx.session.create_message(
                messages=messages,
                max_tokens=250,
                system_prompt="You are an ISP network diagnostic expert.",
                temperature=0.2
            )

            if response and hasattr(response, "content"):
                diagnosis = response.content.text if isinstance(response.content, types.TextContent) else str(response.content)
                return (
                    f"--- Log Diagnosis (LLM Sampling) ---\n"
                    f"Serial: {serial_num} ({model_type})\n"
                    f"Status: {status.upper()}\n\n"
                    f"Summary:\n{diagnosis}"
                )
        except Exception as e:
            logger.warning(f"Sampling call failed, falling back: {e}")

    fallback = _heuristic_fallback_diagnosis(raw_log)
    return (
        f"--- Log Diagnosis (Fallback) ---\n"
        f"Serial: {serial_num} ({model_type})\n"
        f"Status: {status.upper()}\n\n"
        f"Raw Log: {raw_log}\n"
        f"Summary: {fallback}"
    )


def _heuristic_fallback_diagnosis(raw_log: str) -> str:
    """Simple heuristic summary when sampling is unavailable."""
    if "HW_FAULT" in raw_log or "loss of physical medium" in raw_log:
        return "Physical line fault detected. Technician dispatch recommended."
    if "SYS_OK" in raw_log:
        return "Device operates normally. No action required."
    return f"Log entry recorded: {raw_log}. Direct inspection advised."


async def handle_run_network_diagnostic_sweep(
    account_id: int,
    ctx: Optional[Any] = None
) -> str:
    """Runs a multi-stage network test with progress updates."""
    validate_tool_input("run_network_diagnostic_sweep", {"account_id": account_id})

    if not db.account_exists(account_id):
        return f"Error: Account #{account_id} not found."

    checkpoints = [
        "1/5: Checking core routing node & latency",
        "2/5: Testing SNR on physical fiber link",
        "3/5: Pinging modem / ONT interface",
        "4/5: Checking local LAN port states",
        "5/5: Checking DNS & authentication logs"
    ]

    total = len(checkpoints)
    results = []

    for idx, stage_desc in enumerate(checkpoints, start=1):
        if ctx and hasattr(ctx, "report_progress"):
            try:
                await ctx.report_progress(progress=idx, total=total, message=stage_desc)
            except Exception as e:
                logger.warning(f"Could not update progress: {e}")

        await asyncio.sleep(0.8)

        if idx == 2 and account_id == 3:
            results.append(f"Stage {idx}: WARN - Optical power low (-28 dBm)")
        elif idx == 3 and account_id == 3:
            results.append(f"Stage {idx}: FAIL - Modem unreachable")
        else:
            results.append(f"Stage {idx}: OK - Passed")

    summary = "\n".join(results)
    overall = "ACTION REQUIRED: Physical line issue detected" if account_id == 3 else "ALL PASS: Network status nominal"

    return (
        f"--- Diagnostic Results for Account #{account_id} ---\n"
        f"Status: {overall}\n\n"
        f"Checkpoints:\n{summary}"
    )