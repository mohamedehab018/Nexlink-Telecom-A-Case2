"""Decomposition-first planning, adapted from the reference toolkit
(AmrSheta22/task_decomposition_and_planning) for the Nexlink planning agent.

The whole plan is generated up front in one shot, validated as a DAG, then
executed in topological order. The upstream toolkit executes every node with
the LLM; this fork routes nodes that are bound to a real MCP tool
(Task.kind == "tool") through the live server handlers, database and auth
gate, and only uses the LLM for the nodes that genuinely need reasoning.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field

from ..models import Plan, Task


PLANNER_SYSTEM = """You are a careful task-decomposition planner for Nextlink, an ISP.
Produce a small executable DAG, not a prose checklist. Every task must make a concrete
contribution to the goal. Independent lookup or analysis tasks should be parallel.
The plan must end with exactly one synthesis task depending on every necessary branch.

When a sub-task maps 1:1 onto a real Nexlink MCP tool, emit it as a tool node:
  kind = "tool", tool = <tool name>, args = {<parameter>: <value>}.
The available tools are:
  - get_account_summary(account_id)          fetch the customer's plan and address
  - list_support_tickets(account_id)         open/closed tickets for the account
  - get_equipment_diagnostics(account_id)    registered devices and their error logs
  - search_account_by_name(customer_name)    resolve a customer name to an account_id
  - diagnose_equipment_issue(serial_num)     interpret a raw device error log
  - run_network_diagnostic_sweep(account_id) multi-stage line test
  - verify_account_identity(account_id, account_pin) unlock write tools for the session
  - create_support_ticket(account_id, ticket_type, description)
  - schedule_technician_dispatch(account_id, description)   ~$150 truck-roll cost
  - apply_billing_credit(account_id, ticket_id, amount_usd) requires supervisor approval > $25

Write tools require the session to be verified first. Analysis, judgement and
synthesis steps have kind = "llm" / "synthesis" and no tool binding.
Never invent a tool name that is not in this list."""


class PlannedTask(BaseModel):
    """Wire schema; richer semantic constraints are applied by the Task domain model."""

    model_config = ConfigDict(extra="forbid")

    id: str
    instruction: str
    depends_on: list[str]
    kind: str = Field(default="llm", pattern=r"^(tool|llm|synthesis)$")
    tool: str | None = None
    args: dict[str, object] | None = None


class GeneratedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str
    tasks: list[PlannedTask]


def decompose_goal(goal: str, llm: BaseChatModel) -> Plan:
    """Generate the entire DAG up front in one LLM call, then validate it."""
    generated = llm.with_structured_output(
        GeneratedPlan,
        method="json_schema",
    ).invoke([
        ("system", PLANNER_SYSTEM),
        ("human", f"""Decompose this goal into 3-6 tasks: {goal!r}
Use short task ids such as t1. Dependencies may refer only to tasks in the plan.
Preserve the supplied goal exactly in the plan's goal field."""),
    ], temperature=0.1)
    # The caller's goal remains authoritative even if the model paraphrases it.
    payload = generated.model_dump()
    payload["goal"] = goal
    return Plan.model_validate(payload)


def execute_plan(
    plan: Plan,
    llm: BaseChatModel,
    executor: Optional[object] = None,
    credential_provider: Optional[Callable[[int], Optional[int]]] = None,
    max_workers: int = 4,
) -> dict[str, str]:
    """Execute a validated DAG in topological (dependency-safe) batches.

    Nodes bound to a real MCP tool run through `executor.call(tool, args)`;
    the LLM runs every other node. Tool nodes are executed sequentially within
    a batch (they touch a shared, stateful session and a single SQLite db);
    independent LLM reasoning nodes still run in parallel, as upstream.

    A `verify_account_identity` node is planned structurally -- the 4-digit PIN
    is only knowable at execution time, so it is filled from `credential_provider`
    (the support staff) when the node runs. If no PIN is available the node
    records an "AWAITING USER" observation and the plan continues.

    Decomposition-first deliberately executes the plan exactly as planned:
    a tool node that fails at runtime (e.g. a write rejected by the auth gate)
    is recorded as its output and the plan continues. Adapting to such a
    failure is the dynamic decomposition's job, not this one's.
    """
    outputs: dict[str, str] = {}
    for batch in plan.execution_batches():
        tool_tasks: list[Task] = []
        llm_tasks: list[Task] = []
        for task_id in batch:
            (tool_tasks if plan.task(task_id).kind == "tool" else llm_tasks).append(
                plan.task(task_id)
            )

        for task in tool_tasks:
            if executor is None:
                raise RuntimeError(
                    f"Node '{task.id}' is bound to tool '{task.tool}' but no MCP executor was supplied"
                )
            outputs[task.id] = executor.call(task.tool or "", _resolve_args(task, credential_provider))

        if llm_tasks:
            prompts = {
                task.id: _llm_prompt(plan, task, outputs)
                for task in llm_tasks
            }
            with ThreadPoolExecutor(max_workers=min(max_workers, len(llm_tasks))) as pool:
                futures = {
                    pool.submit(
                        llm.invoke,
                        [
                            ("system", "You execute one node in a validated task DAG."),
                            ("human", prompt),
                        ],
                        temperature=0.2,
                    ): task_id
                    for task_id, prompt in prompts.items()
                }
                for future in as_completed(futures):
                    content = future.result().content
                    if not isinstance(content, str) or not content.strip():
                        raise RuntimeError("The chat model returned an empty or unsupported response")
                    outputs[futures[future]] = content.strip()
    return outputs


def _resolve_args(
    task: Task,
    credential_provider: Optional[Callable[[int], Optional[int]]] = None,
) -> dict[str, object]:
    """Fill the staff-supplied PIN into a structurally-planned verify node."""
    args = dict(task.args or {})
    if task.tool == "verify_account_identity" and args.get("account_pin") is None:
        if credential_provider is not None:
            pin = credential_provider(int(args.get("account_id", 0)))
            if pin is not None:
                args["account_pin"] = pin
    return args


def _dependency_context(plan: Plan, task: Task, outputs: dict[str, str]) -> str:
    return "\n\n".join(
        f"OUTPUT FROM {dependency}:\n{outputs[dependency]}"
        for dependency in task.depends_on
    ) or "No prerequisite outputs."


def _llm_prompt(plan: Plan, task: Task, outputs: dict[str, str]) -> str:
    context = _dependency_context(plan, task, outputs)
    return f"""Overall goal: {plan.goal}
Current task: {task.instruction}
Prerequisite outputs:
{context}
Complete only the current task. Be concrete and concise. Do not invent sources."""


def final_output(plan: Plan, outputs: dict[str, str]) -> str:
    terminals = plan.terminal_tasks()
    if len(terminals) != 1:
        raise ValueError(f"Expected exactly one terminal synthesis task, found {terminals}")
    return outputs[terminals[0]]
