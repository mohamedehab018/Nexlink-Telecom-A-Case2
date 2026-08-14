"""Nexlink planning agent -- Task Decomposition & DAG Engine (Person 1 scope).

This package contains the decomposition-first and dynamic/interleaved
decomposition concerns, built on top of the forked reference toolkit in
`planning/planning_lab/` (AmrSheta22/task_decomposition_and_planning) and wired
into the real Nexlink MCP server, database and auth gate through
`planning/mcp_tools.py`.
"""

from .planning_lab.algorithms import (
    DynamicDecision,
    decompose_goal,
    dynamic_decomposition,
    execute_plan,
    final_output,
)
from .planning_lab.models import Plan, Task
from .mcp_tools import MCPToolExecutor

__all__ = [
    "DynamicDecision",
    "MCPToolExecutor",
    "Plan",
    "Task",
    "decompose_goal",
    "dynamic_decomposition",
    "execute_plan",
    "final_output",
]
