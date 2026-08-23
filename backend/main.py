"""FastAPI Backend for Nexlink Telecom.

Run with: uvicorn backend.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import tickets, failures, health, outages, tools, rag, hitl, chat


app = FastAPI(
    title="Nexlink Telecom API",
    description="Backend API for Nexlink Telecom AI Support System",
    version="1.0.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
app.include_router(failures.router, prefix="/api/failures", tags=["failures"])
app.include_router(outages.router, prefix="/api", tags=["outages"])
app.include_router(tools.router, prefix="/api", tags=["tools"])
app.include_router(rag.router, prefix="/api", tags=["rag"])
app.include_router(hitl.router, prefix="/api/hitl", tags=["hitl"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "service": "Nexlink Telecom API",
        "version": "1.0.0",
        "docs": "/docs"
    }
