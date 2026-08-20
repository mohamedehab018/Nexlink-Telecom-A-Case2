"""Ticket API endpoints."""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from shared.failure_tickets.models import (
    TicketCreate, TicketUpdate, TicketResponse, TicketStatus
)
from shared.failure_tickets.tickets import TicketManager


router = APIRouter()
ticket_mgr = TicketManager()


@router.post("/", response_model=TicketResponse, status_code=201)
def create_ticket(ticket: TicketCreate):
    """Create a new support ticket.
    
    - **account_id**: Customer account ID
    - **ticket_type**: billing, technical, dispatch, or other
    - **description**: Ticket description
    """
    return ticket_mgr.create(ticket)


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(ticket_id: int):
    """Get a ticket by ID."""
    ticket = ticket_mgr.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.put("/{ticket_id}", response_model=TicketResponse)
def update_ticket(ticket_id: int, update: TicketUpdate):
    """Update a ticket.
    
    - **status**: open, ongoing, or closed
    - **description**: Updated description
    """
    ticket = ticket_mgr.update(ticket_id, update)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int):
    """Delete a ticket."""
    if not ticket_mgr.delete(ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")


@router.get("/account/{account_id}", response_model=list[TicketResponse])
def list_account_tickets(account_id: int):
    """List all tickets for an account."""
    return ticket_mgr.list_by_account(account_id)


@router.get("/", response_model=list[TicketResponse])
def list_tickets(
    status: Optional[TicketStatus] = Query(None, description="Filter by status")
):
    """List all tickets, optionally filtered by status."""
    return ticket_mgr.list_all(status)


@router.get("/stats/summary")
def get_ticket_stats():
    """Get ticket statistics by status."""
    return ticket_mgr.count_by_status()
