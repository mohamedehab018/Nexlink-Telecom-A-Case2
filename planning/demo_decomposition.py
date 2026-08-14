"""Demo script showing DAG construction and a simple dynamic decomposition run.

Run as a quick smoke test while the planning package is being developed.
"""
from planning.dag import build_example_dag
from planning.decomposition import dynamic_decomposition


def fake_executor(name: str, payload: dict):
    print(f"Executing subtask: {name} with payload {payload}")
    # simple simulated results
    if name == "identify_affected_appointments":
        return {"affected_count": 5}
    if name == "rank_by_urgency":
        return {"order": [101, 102, 103, 104, 105]}
    if name == "propose_reshuffle":
        return {"proposal_id": "p-123", "conflicts": False}
    if name == "call_customers":
        return {"called": 4, "answered": 3}
    return {"status": "ok"}


def demo():
    dag = build_example_dag()
    print("Nodes:", dag.nodes())
    print("Edges:", dag.edges())
    print("Topological order:", dag.topo_sort())

    print("\nRunning dynamic decomposition demo:\n")
    results = dynamic_decomposition(fake_executor, "reshuffle Tuesday board")
    for name, res in results:
        print(f"Result for {name}: {res}")


if __name__ == "__main__":
    demo()
