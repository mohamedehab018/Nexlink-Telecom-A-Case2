"""LangGraph workflow for a durable SLA-dispute review."""
from langgraph.graph import END, StateGraph

from .checkpointing import SLACheckpointManager
from .hitl import create_hitl_request, request_admin_decision
from .nodes import (analyze_dispute, complete_dispute, create_failure_ticket,
                    determine_liability, evaluate_hitl_requirement, mark_failure,
                    receive_dispute, select_root_cause, store_root_cause_candidates,
                    store_sla_evidence)
from .states import SLADisputeState


def build_sla_dispute_graph(checkpoint_manager: SLACheckpointManager | None = None):
    manager = checkpoint_manager or SLACheckpointManager()
    graph = StateGraph(SLADisputeState)
    for name, node in {
        "receive_dispute": receive_dispute, "analyze_dispute": analyze_dispute,
        "store_root_cause_candidates": store_root_cause_candidates,
        "select_root_cause": select_root_cause, "store_sla_evidence": store_sla_evidence,
        "determine_liability": determine_liability, "evaluate_hitl_requirement": evaluate_hitl_requirement,
        "create_hitl_request": create_hitl_request, "request_admin_decision": request_admin_decision, "complete_dispute": complete_dispute,
        "mark_failure": mark_failure, "create_failure_ticket": create_failure_ticket,
    }.items():
        graph.add_node(name, node)
    graph.set_entry_point("receive_dispute")
    for left, right in zip(("receive_dispute", "analyze_dispute", "store_root_cause_candidates", "select_root_cause", "store_sla_evidence", "determine_liability"), ("analyze_dispute", "store_root_cause_candidates", "select_root_cause", "store_sla_evidence", "determine_liability", "evaluate_hitl_requirement")):
        graph.add_edge(left, right)
    graph.add_edge("evaluate_hitl_requirement", "create_hitl_request")
    graph.add_edge("create_hitl_request", "request_admin_decision")
    graph.add_conditional_edges("request_admin_decision", lambda state: "complete_dispute" if state.get("admin_decision") == "approve" else "mark_failure")
    graph.add_edge("complete_dispute", END)
    graph.add_edge("mark_failure", "create_failure_ticket")
    graph.add_edge("create_failure_ticket", END)
    compiled = graph.compile(checkpointer=manager.get_checkpointer())
    # Keep the manager alive for as long as the graph is: its context manager
    # closes the underlying sqlite connection when garbage-collected, which
    # otherwise kills the checkpointer right after this function returns.
    compiled._sla_checkpoint_manager = manager
    return compiled
