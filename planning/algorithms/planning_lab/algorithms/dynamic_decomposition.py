"""Dynamic / interleaved decomposition, adapted from the reference toolkit
(AmrSheta22/task_decomposition_and_planning) for the Nexlink planning agent.

The next sub-task is decided only after observing the result of the previous
one, so an early surprise (a write rejected by the auth gate, a diagnostic
that rules out a dispatch, ...) can reshape what comes next. The decision
step can name a real MCP tool, in which case the observation is the actual
tool result; otherwise the sub-task runs as an LLM reasoning step.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field

DYNAMIC_SYSTEM = """You are an adaptive planner for Nextlink, an ISP.
Use prior observations before deciding what comes next. When the next step
maps onto a real Nexlink MCP tool, set `tool` and `tool_args`:
  - get_account_summary(account_id)
  - list_support_tickets(account_id)
  - get_equipment_diagnostics(account_id)
  - search_account_by_name(customer_name)
  - diagnose_equipment_issue(serial_num)
  - run_network_diagnostic_sweep(account_id)
  - verify_account_identity(account_id, account_pin)   # unlock write tools
  - create_support_ticket(account_id, ticket_type, description)
  - schedule_technician_dispatch(account_id, description)   # ~$150 cost
  - apply_billing_credit(account_id, ticket_id, amount_usd) # supervisor > $25

Rules:
  - Write tools require a verified session. If a previous observation is a
    SECURITY ERROR ("Session unverified"), next emit a verify_account_identity
    node with the failing account_id and no pin (the staff supplies it).
  - When a verification step needs the staff's PIN, set tool to
    verify_account_identity and leave account_pin out of tool_args.
  - For pure reasoning / judgement / synthesis steps, leave tool empty and put
    the instruction in next_task.
Never invent a tool name that is not in this list."""


class DynamicDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: bool
    next_task: str = ""
    tool: str | None = None
    tool_args: dict[str, Any] | None = None


def dynamic_decomposition(
    goal: str,
    llm: BaseChatModel,
    executor: Optional[object] = None,
    credential_provider: Optional[Callable[[int], Optional[int]]] = None,
    max_steps: int = 8,
) -> list[tuple[str, str]]:
    """Interleave planning and execution against real tool observations.

    Each loop iteration:
      1. observes every completed sub-task so far,
      2. asks the planner for the single best next sub-task (tool or reasoning),
      3. executes it -- via the real MCP executor when it is a tool node,
      4. feeds the real result back as the observation for the next decision.

    A `credential_provider` is a callable(account_id) -> pin that stands in
    for the support staff typing their 4-digit PIN when the agent has to
    verify an unverified session. If no pin is available, the loop stops with
    an "AWAITING USER" observation instead of guessing.
    """
    history: list[tuple[str, str]] = []
    for step in range(max_steps):
        observation = "\n".join(f"{task}: {result}" for task, result in history) or "None"
        decision = llm.with_structured_output(
            DynamicDecision,
            method="json_schema",
        ).invoke([
            ("system", DYNAMIC_SYSTEM),
            ("human", f"""Goal: {goal}
Completed work and observations:
{observation}

Decide the single best next task. Set done to true only when the goal is met.
When done is true, leave next_task, tool and tool_args empty."""),
        ], temperature=0.1)

        if decision.done:
            break

        if decision.tool:
            if executor is None:
                raise RuntimeError(
                    f"Decision requested tool '{decision.tool}' but no MCP executor was supplied"
                )
            args = dict(decision.tool_args or {})
            if decision.tool == "verify_account_identity":
                if args.get("account_pin") is None and credential_provider is not None:
                    account_id = int(args.get("account_id", 0))
                    pin = credential_provider(account_id)
                    if pin is None:
                        history.append(
                            (f"REQ-PIN for account #{account_id}",
                             "AWAITING USER: support staff must supply the 4-digit PIN.")
                        )
                        break
                    args["account_pin"] = pin
            label = f"{decision.tool}({args})"
            result = executor.call(decision.tool, args)
        else:
            task = decision.next_task.strip()
            if not task:
                raise ValueError(f"Dynamic planner omitted next_task at step {step + 1}")
            label = task
            response = llm.invoke([
                ("system", "Execute the next adaptive sub-task using the observations provided."),
                ("human", f"Goal: {goal}\nNext task: {task}\nPrior observations:\n{observation}"),
            ], temperature=0.2)
            result = response.content
            if not isinstance(result, str) or not result.strip():
                raise RuntimeError("The chat model returned an empty or unsupported response")
            result = result.strip()

        history.append((label, result))
    return history
