"""Zedcloud MCP server (stdio) — tools wrap the ``zedcloud`` SDK only."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer

from zedcloud import ZedcloudClient
from zedcloud_mcp.tools import TOOL_SPECS

mcp = MCPServer(
    name="zedcloud",
    instructions=(
        "ZEDEDA Zedcloud control-plane tools. Authenticate via "
        "ZEDCLOUD_BASE_URL and ZEDCLOUD_TOKEN environment variables."
    ),
)

_client: ZedcloudClient | None = None


def get_client() -> ZedcloudClient:
    global _client
    if _client is None:
        _client = ZedcloudClient.from_env()
    return _client


def _dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        return json.dumps(
            value.model_dump(mode="json", by_alias=True),
            indent=2,
            default=str,
        )
    return json.dumps(value, indent=2, default=str)


def _register(name: str, description: str, handler: Callable[..., str]) -> None:
    mcp.tool(name=name, description=description)(handler)


def _build_tools() -> None:
    for spec in TOOL_SPECS:
        _register(spec.name, spec.description, spec.bind(get_client, _dump))


def list_tool_names() -> list[str]:
    """Return registered tool names (for make mcp-list / tests)."""
    return sorted(spec.name for spec in TOOL_SPECS)


_build_tools()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
