"""State contract for the SLA-dispute graph."""
from typing import List, Optional, TypedDict


class SLADisputeState(TypedDict, total=False):
    run_id: str
    customer_id: int
    claim_details: str
    current_state: str
    root_cause_candidates: List[str]
    selected_root_cause: Optional[str]
    # Tree-of-Thoughts artefacts from the select_root_cause node
    root_cause_reasoning: Optional[str]
    tot_branches: Optional[List[dict]]
    root_cause_evidence: List[str]
    retrieved_documents: List[str]
    sla_terms: Optional[str]
    liability_decision: Optional[str]
    liability_reasoning: Optional[str]
    hitl_required: bool
    hitl_task_id: Optional[int]
    admin_decision: Optional[str]
    customer_response: Optional[str]
    customer_reply: Optional[str]
    failure_ticket_id: Optional[int]
    error: Optional[str]
