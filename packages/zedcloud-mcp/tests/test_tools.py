"""MCP server smoke tests (no live credentials required)."""

from __future__ import annotations

from zedcloud_mcp.server import list_tool_names


def test_lists_expected_tools() -> None:
    names = list_tool_names()
    assert "zedcloud_list_nodes" in names
    assert "zedcloud_list_apps" in names
    assert "zedcloud_list_networks" in names
    assert "zedcloud_list_zks_instances" in names
    assert "zedcloud_list_jobs" in names
    assert len(names) >= 10
