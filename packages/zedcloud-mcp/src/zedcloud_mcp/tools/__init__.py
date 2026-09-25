"""MCP tool specs grouped by domain."""

from zedcloud_mcp.tools.apps import APP_TOOLS
from zedcloud_mcp.tools.base import ToolSpec
from zedcloud_mcp.tools.jobs import JOB_TOOLS
from zedcloud_mcp.tools.k8s import K8S_TOOLS
from zedcloud_mcp.tools.networks import NETWORK_TOOLS
from zedcloud_mcp.tools.nodes import NODE_TOOLS

TOOL_SPECS: list[ToolSpec] = [
    *NODE_TOOLS,
    *APP_TOOLS,
    *NETWORK_TOOLS,
    *K8S_TOOLS,
    *JOB_TOOLS,
]

__all__ = ["TOOL_SPECS", "ToolSpec"]
