"""Node-related MCP tools."""

from __future__ import annotations

from zedcloud_mcp.tools.base import ClientFactory, DumpFn, Handler, ToolSpec


def _list_nodes(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def list_nodes(
        name_pattern: str | None = None,
        project_name: str | None = None,
        page_size: float = 25,
    ) -> str:
        """List edge nodes (devices)."""
        result = get_client().nodes.query_edge_nodes(
            name_pattern=name_pattern,
            project_name=project_name,
            next_page_size=page_size,
            summary=True,
        )
        return dump(result)

    return list_nodes


def _get_node(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def get_node(node_id: str) -> str:
        """Get an edge node by ID."""
        return dump(get_client().nodes.get_edge_node(node_id))

    return get_node


def _get_node_by_name(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def get_node_by_name(name: str) -> str:
        """Get an edge node by name."""
        return dump(get_client().nodes.get_edge_node_by_name(name))

    return get_node_by_name


def _get_node_status(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def get_node_status(node_id: str) -> str:
        """Get edge node status by ID."""
        return dump(get_client().nodes.get_edge_node_status(node_id))

    return get_node_status


NODE_TOOLS = [
    ToolSpec(
        name="zedcloud_list_nodes",
        description="List edge nodes (devices), optionally filtered by name/project.",
        make_handler=_list_nodes,
    ),
    ToolSpec(
        name="zedcloud_get_node",
        description="Get an edge node configuration by ID.",
        make_handler=_get_node,
    ),
    ToolSpec(
        name="zedcloud_get_node_by_name",
        description="Get an edge node configuration by name.",
        make_handler=_get_node_by_name,
    ),
    ToolSpec(
        name="zedcloud_get_node_status",
        description="Get edge node status/details by ID.",
        make_handler=_get_node_status,
    ),
]
