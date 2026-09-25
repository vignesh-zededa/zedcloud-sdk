"""App-related MCP tools."""

from __future__ import annotations

from zedcloud_mcp.tools.base import ClientFactory, DumpFn, Handler, ToolSpec


def _list_apps(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def list_apps(
        name_pattern: str | None = None,
        page_size: float = 25,
    ) -> str:
        """List edge application bundles."""
        result = get_client().apps.query_edge_application_bundles(
            name_pattern=name_pattern,
            next_page_size=page_size,
            summary=True,
        )
        return dump(result)

    return list_apps


def _get_app(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def get_app(app_id: str) -> str:
        """Get an edge application bundle by ID."""
        return dump(get_client().apps.get_edge_application_bundle(app_id))

    return get_app


def _list_app_instances(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def list_app_instances(
        name_pattern: str | None = None,
        project_name: str | None = None,
        page_size: float = 25,
    ) -> str:
        """List edge application instances."""
        result = get_client().apps.query_edge_application_instances(
            name_pattern=name_pattern,
            project_name=project_name,
            next_page_size=page_size,
            summary=True,
        )
        return dump(result)

    return list_app_instances


def _get_app_instance(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def get_app_instance(instance_id: str) -> str:
        """Get an edge application instance by ID."""
        return dump(get_client().apps.get_edge_application_instance(instance_id))

    return get_app_instance


APP_TOOLS = [
    ToolSpec(
        name="zedcloud_list_apps",
        description="List edge application bundles.",
        make_handler=_list_apps,
    ),
    ToolSpec(
        name="zedcloud_get_app",
        description="Get an edge application bundle by ID.",
        make_handler=_get_app,
    ),
    ToolSpec(
        name="zedcloud_list_app_instances",
        description="List edge application instances.",
        make_handler=_list_app_instances,
    ),
    ToolSpec(
        name="zedcloud_get_app_instance",
        description="Get an edge application instance by ID.",
        make_handler=_get_app_instance,
    ),
]
