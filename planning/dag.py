"""Simple DAG implementation for task decomposition.

Provides node/edge management, cycle detection, and topological ordering.
This is the execution substrate for decomposition-first planning.
"""
from typing import Dict, List, Set, Iterable


class CycleError(Exception):
    pass


class DAG:
    def __init__(self):
        # adjacency list: node -> set of successor nodes
        self._adj: Dict[str, Set[str]] = {}

    def add_node(self, node: str) -> None:
        self._adj.setdefault(node, set())

    def add_edge(self, src: str, dst: str) -> None:
        if src == dst:
            raise CycleError(f"Self-edge would create a cycle: {src} -> {dst}")
        self.add_node(src)
        self.add_node(dst)
        self._adj[src].add(dst)
        if self._has_cycle():
            # roll back
            self._adj[src].remove(dst)
            raise CycleError(f"Adding edge would create a cycle: {src} -> {dst}")

    def nodes(self) -> List[str]:
        return list(self._adj.keys())

    def edges(self) -> List[tuple]:
        return [(s, d) for s, dsts in self._adj.items() for d in dsts]

    def _has_cycle(self) -> bool:
        visited: Set[str] = set()
        onstack: Set[str] = set()

        def dfs(n: str) -> bool:
            visited.add(n)
            onstack.add(n)
            for m in self._adj.get(n, ()):  # type: ignore
                if m not in visited:
                    if dfs(m):
                        return True
                elif m in onstack:
                    return True
            onstack.remove(n)
            return False

        for node in list(self._adj.keys()):
            if node not in visited:
                if dfs(node):
                    return True
        return False

    def topo_sort(self) -> List[str]:
        """Return a topological ordering of nodes.

        Raises CycleError if a cycle exists.
        """
        # Kahn's algorithm
        indeg: Dict[str, int] = {n: 0 for n in self._adj}
        for src, dsts in self._adj.items():
            for d in dsts:
                indeg[d] = indeg.get(d, 0) + 1

        queue: List[str] = [n for n, deg in indeg.items() if deg == 0]
        order: List[str] = []

        while queue:
            n = queue.pop(0)
            order.append(n)
            for m in list(self._adj.get(n, ())):
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)

        if len(order) != len(self._adj):
            raise CycleError("Cycle detected during topological sort")
        return order


def build_example_dag() -> DAG:
    """Builds an example DAG for demo/testing purposes."""
    dag = DAG()
    dag.add_node("identify_affected_appointments")
    dag.add_node("rank_by_urgency")
    dag.add_node("propose_reshuffle")
    dag.add_node("call_customers")
    dag.add_edge("identify_affected_appointments", "rank_by_urgency")
    dag.add_edge("rank_by_urgency", "propose_reshuffle")
    dag.add_edge("propose_reshuffle", "call_customers")
    return dag
