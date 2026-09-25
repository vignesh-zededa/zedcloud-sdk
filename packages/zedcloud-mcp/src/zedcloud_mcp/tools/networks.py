"""Network-related MCP tools."""

from __future__ import annotations

from zedcloud_mcp.tools.base import ClientFactory, DumpFn, Handler, ToolSpec


def _list_networks(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def list_networks(
        name_pattern: str | None = None,
        project_name: str | None = None,
        page_size: float = 25,
    ) -> str:
        """List edge networks."""
        result = get_client().networks.query_edge_networks(
            name_pattern=name_pattern,
            project_name=project_name,
            next_page_size=page_size,
            summary=True,
        )
        return dump(result)

    return list_networks


def _get_network(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def get_network(network_id: str) -> str:
        """Get an edge network by ID."""
        return dump(get_client().networks.get_edge_network(network_id))

    return get_network


def _list_network_instances(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def list_network_instances(
        name_pattern: str | None = None,
        project_name: str | None = None,
        page_size: float = 25,
    ) -> str:
        """List edge network instances."""
        result = get_client().networks.query_edge_network_instances(
            name_pattern=name_pattern,
            project_name=project_name,
            next_page_size=page_size,
            summary=True,
        )
        return dump(result)

    return list_network_instances


NETWORK_TOOLS = [
    ToolSpec(
        name="zedcloud_list_networks",
        description="List edge networks.",
        make_handler=_list_networks,
    ),
    ToolSpec(
        name="zedcloud_get_network",
        description="Get an edge network by ID.",
        make_handler=_get_network,
    ),
    ToolSpec(
        name="zedcloud_list_network_instances",
        description="List edge network instances.",
        make_handler=_list_network_instances,
    ),
]
