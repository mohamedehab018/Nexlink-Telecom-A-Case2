"""LLM-call additions for the order-activation state graph.

Two of the four allowed techniques, each inside a named node:

* Task decomposition — ``decompose_activation_request()`` runs in the START
  node: the raw activation request is broken into an ordered provisioning
  plan (persisted on ``ActivationData.provisioning_plan`` and checkpointed
  with the rest of the state), including the equipment model that fits the
  ordered plan tier instead of a hardcoded default.

* Constrained ReAct — ``run_equipment_react()`` runs across the
  CHECK_EQUIPMENT/CONFIGURE_EQUIPMENT transition: the model reasons
  tool-by-tool but may only call a WHITELIST of read/provision tools.
  Irreversible actions (service activation itself, welcome message) are not
  in the whitelist and stay hard-gated in graph code. Any tool name outside
  the whitelist is refused with an observation, never executed.

Both fail closed: when no LLM is available the callers fall back to the
original deterministic behaviour, so unit tests and offline demos work.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from graphs.llm_additions import chat_json

from . import tools as provision_tools


# ---------------------------------------------------------------------------
# LLM addition #1 — task decomposition (START node)
# ---------------------------------------------------------------------------

DEFAULT_PLAN = [
    "check coverage and equipment stock for the requested plan",
    "assign an equipment model appropriate for the plan tier",
    "configure the equipment for the plan",
    "test the connection",
    "activate service",
]

KNOWN_MODELS = {"Nextlink-WiFi-V3", "Nextlink-Coax-V2", "Nextlink-Optic-V1"}


def decompose_activation_request(
    customer_name: Optional[str],
    address: Optional[str],
    plan_id: Optional[int],
) -> dict[str, Any]:
    """Decompose one activation request into an ordered provisioning plan."""
    verdict = chat_json(
        system=(
            "You plan telecom service activations. Break the request into an "
            "ordered list of concrete provisioning sub-steps, and pick the "
            f"equipment model that fits the plan tier. Known models: "
            f"{sorted(KNOWN_MODELS)}. Respond with ONLY JSON: "
            '{"steps": ["..."], "equipment_model": "<one known model>", '
            '"plan_note": "<one sentence>"}'
        ),
        user=json.dumps({
            "customer_name": customer_name,
            "address": address,
            "plan_id": plan_id,
        }),
    )

    steps: List[str] = []
    model = None
    if verdict:
        raw_steps = verdict.get("steps")
        if isinstance(raw_steps, list):
            steps = [str(s).strip() for s in raw_steps if str(s).strip()]
        model = verdict.get("equipment_model")
        if model not in KNOWN_MODELS:
            model = None

    if not steps:
        # Deterministic fallback keeps offline/test behaviour unchanged.
        return {
            "steps": list(DEFAULT_PLAN),
            "equipment_model": None,
            "plan_note": "default plan (LLM unavailable)",
        }

    return {
        "steps": steps,
        "equipment_model": model,
        "plan_note": str(verdict.get("plan_note", "")).strip(),
    }


# ---------------------------------------------------------------------------
# LLM addition #2 — constrained ReAct (CHECK_EQUIPMENT -> CONFIGURE_EQUIPMENT)
# ---------------------------------------------------------------------------

# The whitelist IS the constraint: nothing outside it can be executed, so
# irreversible actions are structurally out of the model's reach.
TOOL_WHITELIST = {
    "check_equipment_available",
    "assign_equipment",
    "configure_equipment",
}

_MAX_REACT_STEPS = 6


def run_equipment_react(
    account_id: int,
    plan_id: Optional[int],
    preferred_model: Optional[str],
    db_path: str,
) -> Optional[dict[str, Any]]:
    """Reason tool-by-tool over whitelisted provisioning tools.

    Returns ``None`` when the LLM is unavailable or produces unusable output
    (the caller then falls back to the deterministic handler). Otherwise
    returns ``{"success": bool, "error"?: str, "trace": [...], ...}``.
    """
    tools_doc = (
        'check_equipment_available({"model_type": str}) -> availability/cost\n'
        "assign_equipment({\"account_id\": int, \"serial_num\": str, "
        "\"model_type\": str}) -> assigned serial (serial_num may be empty "
        "string \"EQ-<account_id>-001\")\n"
        "configure_equipment({\"serial_num\": str, \"config\": {\"plan_id\": int}})"
        " -> configuration result\n"
        "finish({}) -> provisioning complete"
    )
    observations: List[Dict[str, Any]] = [
        {"step": 0, "observation": f"plan_id={plan_id}, preferred_model={preferred_model}"}
    ]
    serial: Optional[str] = None
    configured = False

    for step in range(1, _MAX_REACT_STEPS + 1):
        decision = chat_json(
            system=(
                "You are a constrained ReAct agent provisioning ISP equipment. "
                "You may ONLY call these tools:\n" + tools_doc + "\n"
                "Anything not in this list is refused by the runtime. Choose "
                "the next single action. Respond with ONLY JSON: "
                '{"tool": "<name or finish>", "args": {...}, '
                '"thought": "<one sentence>"}'
            ),
            user="ACTIONS AND OBSERVATIONS SO FAR:\n"
            + json.dumps(observations, default=str),
        )
        if decision is None:
            return None  # unusable LLM output -> deterministic fallback

        tool = str(decision.get("tool", "")).strip()
        args = decision.get("args") if isinstance(decision.get("args"), dict) else {}

        if tool == "finish":
            if not (serial and configured):
                return {
                    "success": False,
                    "error": "ReAct finished before the equipment was assigned and configured.",
                    "trace": observations,
                }
            return {
                "success": True,
                "serial_num": serial,
                "configured": True,
                "thoughts": [o.get("thought") for o in observations if o.get("thought")],
                "trace": observations,
            }

        if tool not in TOOL_WHITELIST:
            observations.append({
                "step": step,
                "tool": tool,
                "observation": (
                    f"REFUSED: '{tool}' is not on the constrained whitelist."
                    " Allowed: check_equipment_available, assign_equipment,"
                    " configure_equipment, finish."
                ),
                "thought": decision.get("thought"),
            })
            continue

        try:
            if tool == "check_equipment_available":
                result = provision_tools.check_equipment_available(
                    model_type=str(args.get("model_type") or preferred_model or "WiFi-V3"),
                    db_path=db_path,
                )
            elif tool == "assign_equipment":
                result = provision_tools.assign_equipment(
                    account_id=int(args.get("account_id") or account_id),
                    serial_num=str(args.get("serial_num") or f"EQ-{account_id}-001"),
                    model_type=str(args.get("model_type") or preferred_model or "WiFi-V3"),
                    db_path=db_path,
                )
                if isinstance(result, dict) and result.get("success"):
                    serial = result.get("serial_num") or serial
            else:  # configure_equipment
                config_payload = args.get("config") or {"plan_id": plan_id}
                result = provision_tools.configure_equipment(
                    serial_num=str(args.get("serial_num") or serial or ""),
                    config=config_payload,
                    db_path=db_path,
                )
                if isinstance(result, dict) and result.get("success"):
                    configured = True
        except Exception as exc:  # noqa: BLE001 — observation, not crash
            result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}

        observations.append({
            "step": step,
            "tool": tool,
            "args": args,
            "observation": result,
            "thought": decision.get("thought"),
        })

    return {
        "success": False,
        "error": f"ReAct did not finish within {_MAX_REACT_STEPS} steps.",
        "trace": observations,
    }
