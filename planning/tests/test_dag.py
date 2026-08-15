"""DAG substrate: construction-time acyclicity, ordering, and tool binding."""

import pytest

from planning import Plan, Task
from planning.planning_lab.models import NODE_KINDS


def _plan(tasks):
    return Plan.model_validate({"goal": "Resolve a Nexlink incident bundle", "tasks": tasks})


def test_cycle_is_rejected_at_construction():
    with pytest.raises(ValueError, match="Cycle detected"):
        _plan([
            {"id": "a", "instruction": "Fetch diagnostics first", "depends_on": ["b"]},
            {"id": "b", "instruction": "Summarise the incident", "depends_on": ["a"]},
        ])


def test_self_dependency_is_rejected():
    with pytest.raises(ValueError, match="cannot depend on itself"):
        _plan([
            {"id": "a", "instruction": "Fetch diagnostics", "depends_on": ["a"]},
        ])


def test_unknown_dependency_is_rejected():
    with pytest.raises(ValueError, match="unknown dependencies"):
        _plan([
            {"id": "a", "instruction": "Fetch diagnostics", "depends_on": ["ghost"]},
        ])


def test_duplicate_ids_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        _plan([
            {"id": "a", "instruction": "Fetch diagnostics", "depends_on": []},
            {"id": "a", "instruction": "Fetch tickets too", "depends_on": []},
        ])


def test_topological_order_and_parallel_batches():
    plan = _plan([
        {"id": "diag", "instruction": "Fetch equipment diagnostics", "depends_on": []},
        {"id": "tickets", "instruction": "List the open tickets", "depends_on": []},
        {"id": "summary", "instruction": "Synthesise the incident", "depends_on": ["diag", "tickets"]},
    ])
    assert plan.execution_batches() == [["diag", "tickets"], ["summary"]]
    assert plan.topological_order()[-1] == "summary"
    assert plan.terminal_tasks() == ["summary"]


def test_only_one_terminal_task_is_enforced():
    plan = _plan([
        {"id": "diag", "instruction": "Fetch equipment diagnostics", "depends_on": []},
        {"id": "tickets", "instruction": "List the open tickets", "depends_on": []},
    ])
    assert sorted(plan.terminal_tasks()) == ["diag", "tickets"]


def test_dependency_edges_point_from_dependency_to_task():
    plan = _plan([
        {"id": "diag", "instruction": "Fetch equipment diagnostics", "depends_on": []},
        {"id": "dispatch", "instruction": "Dispatch a technician", "depends_on": ["diag"]},
    ])
    assert list(plan.graph.edges) == [("diag", "dispatch")]


def test_tool_binding_must_name_a_tool():
    with pytest.raises(ValueError, match="no tool is bound"):
        _plan([
            {"id": "write", "instruction": "Dispatch a technician", "depends_on": [],
             "kind": "tool", "tool": None},
        ])


def test_tool_on_non_tool_node_is_rejected():
    with pytest.raises(ValueError, match="binds tool"):
        _plan([
            {"id": "reason", "instruction": "Weigh the options", "depends_on": [],
             "kind": "llm", "tool": "get_account_summary"},
        ])


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="kind"):
        Task(id="x", instruction="Something to do", depends_on=[], kind="unknown")


def test_node_kinds_are_exposed():
    assert NODE_KINDS == ("tool", "llm", "synthesis")


def test_valid_tool_binding_is_accepted():
    task = Task(
        id="diag",
        instruction="Fetch equipment diagnostics",
        depends_on=[],
        kind="tool",
        tool="get_equipment_diagnostics",
        args={"account_id": 2},
    )
    assert task.kind == "tool"
    assert task.args == {"account_id": 2}
