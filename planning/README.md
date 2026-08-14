Planning package
================

This folder will host the task decomposition and planning extensions required
by the Decomposition & Planning lab. It will be expanded by wiring the
reference toolkit (github.com/AmrSheta22/task_decomposition_and_planning)
into these adapter modules.

Current contents:
- `dag.py` - a simple DAG implementation with cycle detection and topo sort.
- `decomposition.py` - stubs for decomposition-first and dynamic decomposition.
- `demo_decomposition.py` - a small script demonstrating DAG usage.

Next steps:
- Wire the toolkit's `algorithms/decomposition.py` and
  `algorithms/dynamic_decomposition.py` into `decomposition.py`.
- Implement mapping from DAG nodes to MCP server tool calls.
- Add tests and evaluation harness under `planning_eval/`.
