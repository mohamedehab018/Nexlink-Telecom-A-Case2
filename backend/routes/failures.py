"""Failure API endpoints."""
from fastapi import APIRouter, HTTPException
from shared.failure_tickets.models import (
    FailureLogCreate, FailureLogResponse, FailureAnalysis
)
from shared.failure_tickets.failures import FailureManager
from shared.failure_tickets.service import FailureTicketService


router = APIRouter()
failure_mgr = FailureManager()
service = FailureTicketService()


@router.post("/", response_model=FailureLogResponse, status_code=201)
def log_failure(failure: FailureLogCreate):
    """Log a failure.
    
    - **run_id**: Current run ID
    - **thread_id**: Current thread ID
    - **account_id**: Account that failed
    - **failure_type**: equipment, network, system, configuration, timeout, or unknown
    - **failure_step**: Step where failure occurred
    - **failure_reason**: Why it failed
    - **state_data**: Optional state data at time of failure
    """
    return failure_mgr.log(failure)


@router.get("/{failure_id}", response_model=FailureLogResponse)
def get_failure(failure_id: int):
    """Get a failure log by ID."""
    failure = failure_mgr.get(failure_id)
    if not failure:
        raise HTTPException(status_code=404, detail="Failure not found")
    return failure


@router.get("/account/{account_id}", response_model=list[FailureLogResponse])
def list_account_failures(account_id: int):
    """List all failures for an account."""
    return failure_mgr.list_by_account(account_id)


@router.get("/run/{run_id}", response_model=list[FailureLogResponse])
def list_run_failures(run_id: int):
    """List all failures for a run."""
    return failure_mgr.list_by_run(run_id)


@router.get("/analysis/{account_id}", response_model=FailureAnalysis)
def analyze_failures(account_id: int):
    """Analyze failure patterns for an account."""
    return failure_mgr.analyze(account_id)


@router.post("/handle")
def handle_failure(
    run_id: int,
    thread_id: int,
    account_id: int,
    failure_type: str,
    failure_step: str,
    failure_reason: str,
    retry_count: int = 0,
    max_retries: int = 3
):
    """Handle a failure: log it, create ticket, decide retry.
    
    Returns retry decision with ticket and failure IDs.
    """
    from shared.failure_tickets.models import FailureType
    
    try:
        ft = FailureType(failure_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid failure_type: {failure_type}"
        )
    
    return service.handle_failure(
        run_id=run_id,
        thread_id=thread_id,
        account_id=account_id,
        failure_type=ft,
        failure_step=failure_step,
        failure_reason=failure_reason,
        retry_count=retry_count,
        max_retries=max_retries
    )
