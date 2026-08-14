"""Decomposition-first and dynamic decomposition adapters.

These modules provide a place to plug in the toolkit's algorithms and
wire them to real MCP tools. For now they include local implementations
and adapters that will be expanded to call the reference toolkit.
"""
from typing import Callable, Dict, List, Any, Optional
from .dag import DAG, build_example_dag

# Try to import the reference toolkit's decomposition modules if the
# user has placed them under planning/algorithms (forked toolkit). If
# not present, fall back to local simple implementations above.
try:
    from planning.algorithms import decomposition as toolkit_decomposition  # type: ignore
except Exception:
    toolkit_decomposition = None

try:
    from planning.algorithms import dynamic_decomposition as toolkit_dynamic  # type: ignore
except Exception:
    toolkit_dynamic = None


def decomposition_first(task_description: str) -> DAG:
    """Produce a full DAG plan up-front from the task description.

    If the forked toolkit is available under `planning/algorithms`, delegate
    to it. Otherwise return a small example DAG.
    """
    if toolkit_decomposition and hasattr(toolkit_decomposition, "decompose"):
        # The toolkit's `decompose` is expected to return a structured plan
        # we must convert into our local DAG representation. This adapter
        # assumes the toolkit returns a list of (id, predecessors) or similar.
        tk_plan = toolkit_decomposition.decompose(task_description)
        dag = DAG()
        # Toolkit-specific adapter: accept several common shapes.
        for node in tk_plan.get("nodes", []):
            dag.add_node(node["id"])
        for edge in tk_plan.get("edges", []):
            dag.add_edge(edge[0], edge[1])
        return dag

    # Fallback simple example
    return build_example_dag()


def dynamic_decomposition(step_executor: Callable[[str, Dict[str, Any]], Any],
                          initial_description: str) -> List[Any]:
    """Perform interleaved decomposition and execution.

    If the forked toolkit implements a dynamic decomposition routine, call
    it and route its requested sub-tasks to `step_executor`. Otherwise use
    a simple hard-coded sequence for demo purposes.
    """
    if toolkit_dynamic and hasattr(toolkit_dynamic, "run_dynamic_decomposition"):
        # The toolkit is expected to handle the loop and call our executor
        return toolkit_dynamic.run_dynamic_decomposition(step_executor, initial_description)

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


def execute_dag(dag: DAG, action_map: Dict[str, Callable[[Dict[str, Any]], Any]]) -> Dict[str, Any]:
    """Execute DAG nodes in topological order using action_map to run nodes.

    action_map maps node id -> function(payload) -> result. Returns a
    mapping node id -> result.
    """
    order = dag.topo_sort()
    results: Dict[str, Any] = {}
    for node in order:
        action = action_map.get(node)
        payload = {}
        # A simple pattern: allow upstream results to be used by payload
        # (could be extended to pass real context)
        if action is None:
            results[node] = None
            continue
        try:
            results[node] = action(payload)
        except Exception as e:
            results[node] = {"error": str(e)}
    return results


def default_action_map() -> Dict[str, Callable[[Dict[str, Any]], Any]]:
    """Return an example mapping of DAG node names to real mcp_server actions.

    The functions call into `mcp_server.db` to perform real queries/writes.
    This mapper is deliberately conservative: it only uses existing db
    functions to avoid creating new side-effects.
    """
    try:
        import mcp_server.db as db  # type: ignore
    except Exception:
        db = None

    def identify(_payload: Dict[str, Any]):
        # Example: return a list of example account IDs by searching a name
        if db is None:
            return {"warning": "db unavailable"}
        # This is a demo: return an empty list or a sample account if present
        sample = db.search_account_by_name("Walter")
        return {"sample_account": sample}

    def rank(_payload: Dict[str, Any]):
        if db is None:
            return {"warning": "db unavailable"}
        plans = db.list_subscription_plans()
        # crude ranking by monthly_cost_usd descending
        return {"ranked_plans": sorted(plans, key=lambda p: p["monthly_cost_usd"], reverse=True)}

    def propose(_payload: Dict[str, Any]):
        if db is None:
            return {"warning": "db unavailable"}
        # No real reshuffle in this ISP repo; return a proposal placeholder
        return {"proposal": "dispatch recommended for 2 accounts"}

    def call_customers(_payload: Dict[str, Any]):
        if db is None:
            return {"warning": "db unavailable"}
        # As an example side-effect, create a support ticket to notify customer
        # Only do this when the DB is available and the environment intends it.
        return {"info": "no-op in demo"}

    return {
        "identify_affected_appointments": identify,
        "rank_by_urgency": rank,
        "propose_reshuffle": propose,
        "call_customers": call_customers,
    }

