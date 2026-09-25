"""Unit tests for ZedcloudClient critical paths (httpx mocked via respx)."""

from __future__ import annotations

import httpx
import pytest
import respx
from zedcloud.pagination import collect_all

from zedcloud import AuthError, NotFoundError, ZedcloudClient


def _app_summary(app_id: str, name: str) -> dict:
    return {"id": app_id, "name": name, "originType": "ORIGIN_LOCAL"}


@pytest.fixture
def client() -> ZedcloudClient:
    return ZedcloudClient(
        base_url="https://zedcontrol.example.test",
        token="test-token",
        max_retries=0,
    )


@respx.mock
def test_list_apps_success(client: ZedcloudClient) -> None:
    route = respx.get("https://zedcontrol.example.test/api/v1/apps").mock(
        return_value=httpx.Response(
            200,
            json={
                "list": [_app_summary("app-1", "demo")],
                "next": {"pageToken": "", "pageNum": 1, "pageSize": 10, "totalPages": 1},
            },
        )
    )
    result = client.apps.query_edge_application_bundles(next_page_size=10)
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"
    items = result.list_
    assert items is not None
    assert items[0].id == "app-1"
    assert items[0].name == "demo"


@respx.mock
def test_get_node_not_found(client: ZedcloudClient) -> None:
    respx.get("https://zedcontrol.example.test/api/v1/devices/id/missing").mock(
        return_value=httpx.Response(404, json={"message": "device not found"})
    )
    with pytest.raises(NotFoundError) as exc:
        client.nodes.get_edge_node("missing")
    assert exc.value.status_code == 404


@respx.mock
def test_auth_error(client: ZedcloudClient) -> None:
    respx.get("https://zedcontrol.example.test/api/v1/devices").mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"})
    )
    with pytest.raises(AuthError):
        client.nodes.query_edge_nodes()


@respx.mock
def test_k8s_sends_api_key_header(client: ZedcloudClient) -> None:
    route = respx.get("https://zedcontrol.example.test/api/v1/zks/instances").mock(
        return_value=httpx.Response(200, json={"list": [], "next": {}})
    )
    client.k8s.list_zks_instances()
    assert route.called
    headers = route.calls[0].request.headers
    assert headers["X-API-KEY"] == "test-token"
    assert headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_retries_on_429() -> None:
    client = ZedcloudClient(
        base_url="https://zedcontrol.example.test",
        token="test-token",
        max_retries=2,
        timeout=5,
    )
    # Override backoff to be instant
    client._bearer.retry_backoff = 0
    route = respx.get("https://zedcontrol.example.test/api/v1/apps").mock(
        side_effect=[
            httpx.Response(429, json={"message": "slow down"}),
            httpx.Response(200, json={"list": [], "next": {}}),
        ]
    )
    result = client.apps.query_edge_application_bundles()
    assert route.call_count == 2
    assert not result.list_
    client.close()


@respx.mock
def test_pagination_helper(client: ZedcloudClient) -> None:
    respx.get("https://zedcontrol.example.test/api/v1/apps").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "list": [_app_summary("a1", "one")],
                    "next": {"pageToken": "tok-2", "pageNum": 1, "pageSize": 1, "totalPages": 2},
                },
            ),
            httpx.Response(
                200,
                json={
                    "list": [_app_summary("a2", "two")],
                    "next": {"pageToken": "", "pageNum": 2, "pageSize": 1, "totalPages": 2},
                },
            ),
        ]
    )
    items = collect_all(client.apps.query_edge_application_bundles, page_size=1)
    assert [i.id for i in items] == ["a1", "a2"]


def test_config_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZEDCLOUD_BASE_URL", raising=False)
    monkeypatch.delenv("ZEDCLOUD_TOKEN", raising=False)
    with pytest.raises(ValueError, match="ZEDCLOUD_BASE_URL"):
        ZedcloudClient.from_env()
