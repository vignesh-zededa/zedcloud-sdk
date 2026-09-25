"""Kubernetes / ZKS MCP tools."""

from __future__ import annotations

from zedcloud_mcp.tools.base import ClientFactory, DumpFn, Handler, ToolSpec


def _list_zks_instances(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def list_zks_instances() -> str:
        """List ZKS cluster instances."""
        return dump(get_client().k8s.list_zks_instances())

    return list_zks_instances


def _get_zks_instance(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def get_zks_instance(instance_id: str) -> str:
        """Get a ZKS cluster instance by ID."""
        return dump(get_client().k8s.get_zks_instance(instance_id))

    return get_zks_instance


def _list_k8s_deployments(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def list_k8s_deployments() -> str:
        """List Kubernetes deployments managed by ZKS."""
        return dump(get_client().k8s.list_deployments())

    return list_k8s_deployments


K8S_TOOLS = [
    ToolSpec(
        name="zedcloud_list_zks_instances",
        description="List ZKS (ZEDEDA Kubernetes Service) cluster instances.",
        make_handler=_list_zks_instances,
    ),
    ToolSpec(
        name="zedcloud_get_zks_instance",
        description="Get a ZKS cluster instance by ID.",
        make_handler=_get_zks_instance,
    ),
    ToolSpec(
        name="zedcloud_list_k8s_deployments",
        description="List Kubernetes deployments managed via Zedcloud.",
        make_handler=_list_k8s_deployments,
    ),
]
