"""Health check endpoints."""
from fastapi import APIRouter
from shared.failure_tickets.models import HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check():
    """Health check endpoint."""
    return HealthResponse()
