"""Pydantic models for MCP Runtime Core."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Any
from pydantic import BaseModel, Field


class ToolCapability(str, Enum):
    """Tool capability categories."""
    READ = "read"
    WRITE = "write"
    DIAGNOSTIC = "diagnostic"
    ADMIN = "admin"
    BILLING = "billing"
    DISPATCH = "dispatch"


class ToolCategory(str, Enum):
    """Tool functional categories."""
    ACCOUNT = "account"
    EQUIPMENT = "equipment"
    TICKET = "ticket"
    KNOWLEDGE = "knowledge"
    NETWORK = "network"
    SYSTEM = "system"


class ToolDefinition(BaseModel):
    """Definition of an MCP tool."""
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    capability: ToolCapability
    category: ToolCategory
    enabled: bool = True
    version: str = "1.0.0"
    author: str = "system"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        use_enum_values = True


class ToolDefinitionCreate(BaseModel):
    """Model for creating a tool definition."""
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    capability: ToolCapability
    category: ToolCategory
    version: str = "1.0.0"
    author: str = "system"


class ToolToggle(BaseModel):
    """Model for toggling a tool."""
    enabled: bool


class ToolResponse(BaseModel):
    """Model for tool response."""
    name: str
    description: str
    capability: str
    category: str
    enabled: bool
    version: str
    author: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ToolListResponse(BaseModel):
    """Model for tool list response."""
    tools: list[ToolResponse]
    total: int
    enabled_count: int
    disabled_count: int


class ToolStatsResponse(BaseModel):
    """Model for tool statistics."""
    total: int
    enabled: int
    disabled: int
    by_capability: dict[str, int]
    by_category: dict[str, int]
