"""Registry-driven ``client.call`` and operation search."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zedcloud import AsyncZedcloudClient, ZedcloudClient
from zedcloud.models import DeviceConfig
from zedcloud.operations import get_operation, search_operations


def test_call_by_operation_id(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices/id/d1").mock(return_value=httpx.Response(200, json={"id": "d1"}))
    result = client.call("EdgeNodeConfiguration_GetEdgeNode", path={"id": "d1"})
    assert isinstance(result, DeviceConfig) and route.called


def test_call_by_service_method_and_python_param_names(
    client: ZedcloudClient, api: respx.MockRouter
) -> None:
    route = api.get("/v1/devices").mock(return_value=httpx.Response(200, json={}))
    client.call("nodes.query_edge_nodes", query={"page_size": 3, "namePattern": "gw*"})
    params = route.calls.last.request.url.params
    assert params["next.pageSize"] == "3" and params["namePattern"] == "gw*"


def test_call_normalises_snake_case_bodies(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.put("/v1/devices/id/d1").mock(return_value=httpx.Response(200, json={}))
    client.call("nodes.update_edge_node", path={"id": "d1"}, body={"project_id": "p", "title": "T"})
    assert json.loads(route.calls.last.request.content) == {"projectId": "p", "title": "T"}


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"path": {}}, "missing path parameters"),
        ({"path": {"id": "1", "bogus": 1}}, "unknown path parameter 'bogus'"),
        ({"path": {"id": "1"}, "query": {"nope": 1}}, "unknown query parameter"),
        ({"path": {"id": "1"}, "body": {"a": 1}}, "does not take a request body"),
    ],
)
def test_call_validates_arguments(client: ZedcloudClient, kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        client.call("EdgeNodeConfiguration_GetEdgeNode", **kwargs)


def test_unknown_operation(client: ZedcloudClient) -> None:
    with pytest.raises(KeyError):
        client.call("Nope_Nope")


async def test_async_call(aclient: AsyncZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/devices/id/d1").mock(return_value=httpx.Response(200, json={"id": "d1"}))
    assert (await aclient.call("nodes.get_edge_node", path={"id": "d1"})).id == "d1"


def test_risk_classification() -> None:
    assert get_operation("nodes.get_edge_node").risk == "read"
    assert get_operation("nodes.update_edge_node").risk == "write"
    assert get_operation("nodes.reboot").risk == "destructive"
    assert get_operation("nodes.delete_edge_node").risk == "destructive"
    assert get_operation("nodes.offboard").risk == "destructive"


def test_search_operations() -> None:
    top = [op.operation_id for op in search_operations("reboot edge node", limit=3)]
    assert "EdgeNodeConfiguration_Reboot" in top
    reads = search_operations("list devices", risk="read", limit=5)
    assert reads and all(op.risk == "read" for op in reads)
    assert "EdgeNodeConfiguration_QueryEdgeNodes" in [op.operation_id for op in reads]
