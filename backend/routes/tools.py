"""Tool Management API endpoints."""
from fastapi import APIRouter, HTTPException, Query
from mcp_server.runtime_core.models import (
    ToolDefinition,
    ToolToggle,
    ToolResponse,
    ToolListResponse,
    ToolStatsResponse,
    ToolCapability,
    ToolCategory
)
from mcp_server.runtime_core.manager import MCPToolManager

router = APIRouter()
manager = MCPToolManager()


def _to_response(tool: ToolDefinition) -> ToolResponse:
    return ToolResponse(
        name=tool.name,
        description=tool.description,
        capability=tool.capability,
        category=tool.category,
        enabled=tool.enabled,
        version=tool.version,
        author=tool.author,
        created_at=str(tool.created_at) if tool.created_at else None,
        updated_at=str(tool.updated_at) if tool.updated_at else None
    )


@router.get("/tools", response_model=ToolListResponse)
def list_tools(
    enabled_only: bool = Query(False, description="Only return enabled tools")
):
    """List all registered tools."""
    tools = manager.list_tools(enabled_only=enabled_only)
    responses = [_to_response(t) for t in tools]
    enabled_count = sum(1 for t in tools if t.enabled)
    return ToolListResponse(
        tools=responses,
        total=len(tools),
        enabled_count=enabled_count,
        disabled_count=len(tools) - enabled_count
    )


@router.get("/tools/stats", response_model=ToolStatsResponse)
def get_tool_stats():
    """Get tool statistics."""
    stats = manager.get_stats()
    return ToolStatsResponse(**stats)


@router.get("/tools/{name}", response_model=ToolResponse)
def get_tool(name: str):
    """Get a specific tool by name."""
    tool = manager.get_tool(name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    return _to_response(tool)


@router.post("/tools/{name}/toggle", response_model=ToolResponse)
def toggle_tool(name: str, body: ToolToggle):
    """Enable or disable a tool."""
    tool = manager.toggle_tool(name, body.enabled)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    return _to_response(tool)


@router.get("/tools/capability/{capability}", response_model=ToolListResponse)
def filter_by_capability(capability: ToolCapability):
    """Filter tools by capability."""
    tools = manager.filter_by_capability(capability)
    responses = [_to_response(t) for t in tools]
    enabled_count = sum(1 for t in tools if t.enabled)
    return ToolListResponse(
        tools=responses,
        total=len(tools),
        enabled_count=enabled_count,
        disabled_count=len(tools) - enabled_count
    )


@router.get("/tools/category/{category}", response_model=ToolListResponse)
def filter_by_category(category: ToolCategory):
    """Filter tools by category."""
    tools = manager.filter_by_category(category)
    responses = [_to_response(t) for t in tools]
    enabled_count = sum(1 for t in tools if t.enabled)
    return ToolListResponse(
        tools=responses,
        total=len(tools),
        enabled_count=enabled_count,
        disabled_count=len(tools) - enabled_count
    )
