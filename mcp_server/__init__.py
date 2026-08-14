"""mcp_server package initializer.

Converts the mcp_server folder into a Python package so intra-package
relative imports work when running the server as a module.
"""

__all__ = [
    "server",
    "db",
    "auth",
    "tools_read",
    "tools_write",
    "tools_diagnostic",
    "prompts",
    "resources",
    "schemas",
]
