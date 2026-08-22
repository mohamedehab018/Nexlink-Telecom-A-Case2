"""Core tool manager for MCP Runtime Core."""
from __future__ import annotations
import logging
from typing import Callable, Any, Optional
from .models import ToolDefinition, ToolCapability, ToolCategory, ToolDefinitionCreate
from .db import MCPToolDatabase

logger = logging.getLogger(__name__)


class MCPToolManager:
    """Manages MCP tools at runtime.

    Provides methods to register, deregister, toggle, and filter tools.
    Uses database for persistence and in-memory cache for fast access.
    """

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db = MCPToolDatabase(db_path)
        self._functions: dict[str, Callable] = {}
        self.db.init_db()
        logger.info("MCPToolManager initialized with database: %s", db_path)

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: str,
        capability: ToolCapability,
        category: ToolCategory,
        version: str = "1.0.0",
        author: str = "system"
    ) -> ToolDefinition:
        """Register a new tool with its function."""
        if name in self._functions:
            raise ValueError(f"Tool '{name}' already registered")

        tool_def = ToolDefinition(
            name=name,
            description=description,
            capability=capability,
            category=category,
            enabled=True,
            version=version,
            author=author
        )

        self.db.create_tool(tool_def)
        self._functions[name] = func
        logger.info("Registered tool: %s", name)
        return tool_def

    def deregister_tool(self, name: str) -> bool:
        """Deregister a tool by name."""
        self._functions.pop(name, None)
        deleted = self.db.delete_tool(name)
        if deleted:
            logger.info("Deregistered tool: %s", name)
        return deleted

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name."""
        return self.db.get_tool(name)

    def get_function(self, name: str) -> Optional[Callable]:
        """Get a tool's function by name."""
        return self._functions.get(name)

    def list_tools(self, enabled_only: bool = False) -> list[ToolDefinition]:
        """List all tools."""
        return self.db.list_tools(enabled_only)

    def toggle_tool(self, name: str, enabled: bool) -> Optional[ToolDefinition]:
        """Enable or disable a tool."""
        tool = self.db.toggle_tool(name, enabled)
        if tool:
            logger.info("Toggled tool %s: %s", name, "enabled" if enabled else "disabled")
        return tool

    def filter_by_capability(self, capability: ToolCapability) -> list[ToolDefinition]:
        """Filter tools by capability."""
        return self.db.filter_by_capability(capability)

    def filter_by_category(self, category: ToolCategory) -> list[ToolDefinition]:
        """Filter tools by category."""
        return self.db.filter_by_category(category)

    def get_stats(self) -> dict:
        """Get tool statistics."""
        return self.db.get_stats()

    def execute_tool(self, name: str, **kwargs) -> Any:
        """Execute a tool by name if enabled."""
        tool = self.db.get_tool(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found")
        if not tool.enabled:
            raise ValueError(f"Tool '{name}' is disabled")

        func = self._functions.get(name)
        if not func:
            raise ValueError(f"Tool '{name}' function not loaded")

        logger.info("Executing tool: %s", name)
        return func(**kwargs)
