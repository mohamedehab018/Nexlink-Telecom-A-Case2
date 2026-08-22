"""Database operations for MCP Runtime Core."""
from __future__ import annotations
import sqlite3
from datetime import datetime
from typing import Optional
from .models import ToolDefinition, ToolCapability, ToolCategory


class MCPToolDatabase:
    """Database operations for MCP tools."""

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialize the mcp_tools table."""
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mcp_tools (
                    tool_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    category TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT 1,
                    version TEXT DEFAULT '1.0.0',
                    author TEXT DEFAULT 'system',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def create_tool(self, tool: ToolDefinition) -> ToolDefinition:
        """Insert a new tool into the database."""
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                """
                INSERT INTO mcp_tools (name, description, capability, category, enabled, version, author, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tool.name, tool.description, tool.capability, tool.category, tool.enabled, tool.version, tool.author, now, now)
            )
            conn.commit()
            tool.created_at = now
            tool.updated_at = now
            return tool
        finally:
            conn.close()

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM mcp_tools WHERE name = ?", (name,)).fetchone()
            if row:
                return ToolDefinition(
                    name=row["name"],
                    description=row["description"],
                    capability=row["capability"],
                    category=row["category"],
                    enabled=bool(row["enabled"]),
                    version=row["version"],
                    author=row["author"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
            return None
        finally:
            conn.close()

    def list_tools(self, enabled_only: bool = False) -> list[ToolDefinition]:
        """List all tools, optionally filtered by enabled status."""
        conn = self._get_conn()
        try:
            if enabled_only:
                rows = conn.execute("SELECT * FROM mcp_tools WHERE enabled = 1").fetchall()
            else:
                rows = conn.execute("SELECT * FROM mcp_tools").fetchall()
            return [
                ToolDefinition(
                    name=row["name"],
                    description=row["description"],
                    capability=row["capability"],
                    category=row["category"],
                    enabled=bool(row["enabled"]),
                    version=row["version"],
                    author=row["author"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
                for row in rows
            ]
        finally:
            conn.close()

    def update_tool(self, name: str, **kwargs) -> Optional[ToolDefinition]:
        """Update a tool's fields."""
        conn = self._get_conn()
        try:
            allowed = {"description", "capability", "category", "enabled", "version", "author"}
            updates = {k: v for k, v in kwargs.items() if k in allowed}
            if not updates:
                return self.get_tool(name)
            updates["updated_at"] = datetime.now().isoformat()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [name]
            conn.execute(f"UPDATE mcp_tools SET {set_clause} WHERE name = ?", values)
            conn.commit()
            return self.get_tool(name)
        finally:
            conn.close()

    def delete_tool(self, name: str) -> bool:
        """Delete a tool by name."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("DELETE FROM mcp_tools WHERE name = ?", (name,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def toggle_tool(self, name: str, enabled: bool) -> Optional[ToolDefinition]:
        """Enable or disable a tool."""
        return self.update_tool(name, enabled=enabled)

    def filter_by_capability(self, capability: ToolCapability) -> list[ToolDefinition]:
        """Filter tools by capability."""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM mcp_tools WHERE capability = ? AND enabled = 1", (capability.value,)).fetchall()
            return [
                ToolDefinition(
                    name=row["name"],
                    description=row["description"],
                    capability=row["capability"],
                    category=row["category"],
                    enabled=bool(row["enabled"]),
                    version=row["version"],
                    author=row["author"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
                for row in rows
            ]
        finally:
            conn.close()

    def filter_by_category(self, category: ToolCategory) -> list[ToolDefinition]:
        """Filter tools by category."""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM mcp_tools WHERE category = ? AND enabled = 1", (category.value,)).fetchall()
            return [
                ToolDefinition(
                    name=row["name"],
                    description=row["description"],
                    capability=row["capability"],
                    category=row["category"],
                    enabled=bool(row["enabled"]),
                    version=row["version"],
                    author=row["author"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
                for row in rows
            ]
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """Get tool statistics."""
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM mcp_tools").fetchone()[0]
            enabled = conn.execute("SELECT COUNT(*) FROM mcp_tools WHERE enabled = 1").fetchone()[0]

            cap_rows = conn.execute("SELECT capability, COUNT(*) as count FROM mcp_tools GROUP BY capability").fetchall()
            cat_rows = conn.execute("SELECT category, COUNT(*) as count FROM mcp_tools GROUP BY category").fetchall()

            return {
                "total": total,
                "enabled": enabled,
                "disabled": total - enabled,
                "by_capability": {row["capability"]: row["count"] for row in cap_rows},
                "by_category": {row["category"]: row["count"] for row in cat_rows}
            }
        finally:
            conn.close()
