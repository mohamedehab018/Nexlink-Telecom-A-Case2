"""Nexlink planning agent -- Task Decomposition & DAG Engine (Person 1 scope),
extended with Self-Correction + Integration (Person 3 scope: `self_refine`,
`reflexion`, `GroundedEnvironment`, `resolve_with_self_correction`).

This package contains the decomposition-first and dynamic/interleaved
decomposition concerns, built on top of the forked reference toolkit in
`planning/planning_lab/` (AmrSheta22/task_decomposition_and_planning) and wired
into the real Nexlink MCP server, database and auth gate through
`planning/mcp_tools.py`.
"""

from .planning_lab.algorithms import (
    DynamicDecision,
    GroundedEnvironment,
    decompose_goal,
    dynamic_decomposition,
    execute_plan,
    final_output,
    reflect_and_refine,
    reflexion,
    ungrounded_critique,
)
from .planning_lab.models import Plan, Task
from .mcp_tools import MCPToolExecutor
from .self_correction import resolve_with_self_correction

__all__ = [
    "DynamicDecision",
    "GroundedEnvironment",
    "MCPToolExecutor",
    "Plan",
    "Task",
    "decompose_goal",
    "dynamic_decomposition",
    "execute_plan",
    "final_output",
    "reflect_and_refine",
    "reflexion",
    "resolve_with_self_correction",
    "ungrounded_critique",
]
