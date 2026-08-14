"""Decomposition-first and dynamic decomposition adapters.

These modules provide a place to plug in the toolkit's algorithms and
wire them to real MCP tools. For now they include local implementations
and adapters that will be expanded to call the reference toolkit.
"""
from typing import Callable, Dict, List, Any
from .dag import DAG, build_example_dag


def decomposition_first(task_description: str) -> DAG:
    """Produce a full DAG plan up-front from the task description.

This is a simple placeholder: in a full implementation we would call
the reference toolkit's decomposition module with task-specific prompts
and then construct a DAG whose nodes are concrete subtask identifiers
and payloads.
"""
    # TODO: replace with toolkit-driven decomposition (algorithms/decomposition.py)
    dag = build_example_dag()
    return dag


def dynamic_decomposition(step_executor: Callable[[str, Dict[str, Any]], Any],
                          initial_description: str) -> List[Any]:
    """Perform interleaved decomposition and execution.

    Repeatedly ask a decomposition policy for the next subtask given the
    results so far, execute it, then repeat until completion. This demo
    uses a trivial hard-coded sequence to illustrate the pattern.
    """
    results = []
    # A trivial sequence matching build_example_dag
    sub_tasks = [
        ("identify_affected_appointments", {}),
        ("rank_by_urgency", {}),
        ("propose_reshuffle", {}),
        ("call_customers", {}),
    ]

    for name, payload in sub_tasks:
        res = step_executor(name, payload)
        results.append((name, res))
        # dynamic policy could inspect res and decide to reshape the future steps
        # e.g., if a customer doesn't pick up, skip call_customers or re-rank.

    return results
