"""Regression tests for transport safety fixes."""

from __future__ import annotations

import httpx
import pytest
import respx

from zedcloud import ServerError, ZedcloudClient

BASE = "https://zc.example"
DEVICE = {"id": "1", "name": "d", "title": "d", "projectId": "p", "modelId": "m"}


@pytest.fixture
def client() -> ZedcloudClient:
    c = ZedcloudClient(base_url=BASE, token="t", max_retries=2)
    c._bearer.retry_backoff = 0
    return c


@respx.mock(base_url=BASE)
def test_post_is_not_retried_on_5xx(respx_mock: respx.MockRouter, client: ZedcloudClient) -> None:
    route = respx_mock.post("/api/v1/devices").mock(return_value=httpx.Response(503))
    with pytest.raises(ServerError):
        client.nodes.create_edge_node({"name": "x"})
    assert route.call_count == 1


@respx.mock(base_url=BASE)
def test_get_is_retried_on_5xx(respx_mock: respx.MockRouter, client: ZedcloudClient) -> None:
    route = respx_mock.get("/api/v1/devices/id/1").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=DEVICE)]
    )
    assert client.nodes.get_edge_node("1").id == "1"
    assert route.call_count == 2


@respx.mock(base_url=BASE)
def test_post_is_retried_on_429(respx_mock: respx.MockRouter, client: ZedcloudClient) -> None:
    route = respx_mock.post("/api/v1/devices").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json={})]
    )
    client.nodes.create_edge_node({"name": "x"})
    assert route.call_count == 2


@respx.mock(base_url=BASE)
def test_connect_errors_are_retried(respx_mock: respx.MockRouter, client: ZedcloudClient) -> None:
    route = respx_mock.post("/api/v1/devices").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={})]
    )
    client.nodes.create_edge_node({"name": "x"})
    assert route.call_count == 2


@respx.mock(base_url=BASE, assert_all_called=False)
def test_path_params_cannot_escape_their_segment(
    respx_mock: respx.MockRouter, client: ZedcloudClient
) -> None:
    route = respx_mock.get(url__regex=r".*").mock(return_value=httpx.Response(200, json=DEVICE))
    client.nodes.get_edge_node_by_name("site-a/../../v1/users?x=#y")
    url = route.calls.last.request.url
    assert url.raw_path == b"/api/v1/devices/name/site-a%2F..%2F..%2Fv1%2Fusers%3Fx%3D%23y"
    assert not url.query
