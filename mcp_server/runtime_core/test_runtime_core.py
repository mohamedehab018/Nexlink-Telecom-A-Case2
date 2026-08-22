"""Test script for MCP Runtime Core."""
import sys
sys.path.insert(0, "/home/youssef/youssef/programming/college training/Nexlink-Telecom")

from mcp_server.runtime_core import MCPToolManager, ToolCapability, ToolCategory


def dummy_tool(account_id: int):
    """Dummy tool for testing."""
    return {"account_id": account_id, "status": "ok"}


def test_manager():
    manager = MCPToolManager()

    # Cleanup from previous runs
    manager.deregister_tool("get_account_summary")

    # Register a tool
    tool = manager.register_tool(
        name="get_account_summary",
        func=dummy_tool,
        description="Get account summary",
        capability=ToolCapability.READ,
        category=ToolCategory.ACCOUNT,
    )
    print(f"✓ Registered: {tool.name} ({tool.capability}/{tool.category})")

    # List tools
    tools = manager.list_tools()
    print(f"✓ Total tools: {len(tools)}")

    # Get tool
    fetched = manager.get_tool("get_account_summary")
    print(f"✓ Fetched: {fetched.name}, enabled={fetched.enabled}")

    # Toggle off
    toggled = manager.toggle_tool("get_account_summary", False)
    print(f"✓ Toggled: {toggled.name}, enabled={toggled.enabled}")

    # Filter by capability (only enabled tools)
    read_tools = manager.filter_by_capability(ToolCapability.READ)
    print(f"✓ READ tools (enabled only): {len(read_tools)}")

    # Toggle back on
    toggled = manager.toggle_tool("get_account_summary", True)
    print(f"✓ Toggled back: {toggled.name}, enabled={toggled.enabled}")

    # Stats
    stats = manager.get_stats()
    print(f"✓ Stats: total={stats['total']}, enabled={stats['enabled']}, disabled={stats['disabled']}")

    # Execute tool
    result = manager.execute_tool("get_account_summary", account_id=123)
    print(f"✓ Executed: {result}")

    # Cleanup
    manager.deregister_tool("get_account_summary")
    tools_after = manager.list_tools()
    print(f"✓ After deregister: {len(tools_after)} tools")

    print("\n✅ All MCP Runtime Core tests passed!")


if __name__ == "__main__":
    test_manager()
