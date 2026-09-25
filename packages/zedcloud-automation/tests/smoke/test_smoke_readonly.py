"""Read-only smoke tests against a live Zedcloud tenant (skipped without one)."""

from __future__ import annotations

import pytest

from zedcloud import ZedcloudClient

pytestmark = [pytest.mark.smoke, pytest.mark.needs_cloud]


def test_session_identifies_the_tenant(zedcloud_client: ZedcloudClient) -> None:
    assert zedcloud_client.whoami() is not None


def test_list_projects(zedcloud_client: ZedcloudClient) -> None:
    projects = list(zedcloud_client.nodes.iter_resource_groups(max_items=5))
    assert isinstance(projects, list)


def test_list_edge_nodes(zedcloud_client: ZedcloudClient) -> None:
    for node in zedcloud_client.nodes.iter_edge_nodes(summary=True, max_items=5):
        assert node.id and node.name


def test_list_app_bundles(zedcloud_client: ZedcloudClient) -> None:
    for app in zedcloud_client.apps.iter_edge_application_bundles(summary=True, max_items=5):
        assert app.name


def test_edge_node_lookup_round_trip(zedcloud_client: ZedcloudClient) -> None:
    first = next(iter(zedcloud_client.nodes.iter_edge_nodes(max_items=1)), None)
    if first is None:
        pytest.skip("tenant has no edge nodes")
    by_name = zedcloud_client.nodes.lookup_edge_node(first.name)
    by_id = zedcloud_client.nodes.lookup_edge_node(first.id)
    assert by_name.id == by_id.id == first.id
