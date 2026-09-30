"""MCP server exposing ZEDEDA Zedcloud to chat assistants, built on the zedcloud SDK."""

from zedcloud_mcp.server import create_server, main

__all__ = ["create_server", "main"]
__version__ = "0.2.0"
