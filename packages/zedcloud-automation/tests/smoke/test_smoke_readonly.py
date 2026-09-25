"""Read-only smoke tests against a live Zedcloud tenant (skipped without creds)."""

from __future__ import annotations

import pytest

from zedcloud import ZedcloudClient

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.needs_cloud,
]


def test_list_enterprises(zedcloud_client: ZedcloudClient) -> None:
    result = zedcloud_client.iam.query_enterprises(next_page_size=5)
    assert result is not None


def test_list_apps_readonly(zedcloud_client: ZedcloudClient) -> None:
    result = zedcloud_client.apps.query_edge_application_bundles(next_page_size=5, summary=True)
    assert result is not None
    assert hasattr(result, "list")


def test_list_nodes_readonly(zedcloud_client: ZedcloudClient) -> None:
    result = zedcloud_client.nodes.query_edge_nodes(next_page_size=5, summary=True)
    assert result is not None
    assert hasattr(result, "list")
