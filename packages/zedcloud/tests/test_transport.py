"""Transport behaviour: retries, encoding, errors, response decoding."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from zedcloud import (
    ApiError,
    AuthError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ServerError,
    TransportError,
    ZedcloudClient,
)

DEVICE = {"id": "1", "name": "d"}


def test_post_is_not_retried_on_5xx(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.post("/v1/devices").mock(return_value=httpx.Response(503))
    with pytest.raises(ServerError):
        client.nodes.create_edge_node({"name": "x"})
    assert route.call_count == 1


def test_put_actions_are_not_retried_on_5xx(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.put("/v1/devices/id/1/reboot").mock(return_value=httpx.Response(502))
    with pytest.raises(ServerError):
        client.nodes.reboot("1")
    assert route.call_count == 1


def test_get_is_retried_on_5xx(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices/id/1").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=DEVICE)]
    )
    assert client.nodes.get_edge_node("1").id == "1"
    assert route.call_count == 2


def test_retries_keep_the_same_request_id(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices/id/1").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=DEVICE)]
    )
    client.nodes.get_edge_node("1")
    ids = {call.request.headers["X-Request-Id"] for call in route.calls}
    assert len(ids) == 1


def test_any_method_is_retried_on_429(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.post("/v1/devices").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={}),
        ]
    )
    client.nodes.create_edge_node({"name": "x"})
    assert route.call_count == 2


def test_connect_errors_are_retried_then_wrapped(
    client: ZedcloudClient, api: respx.MockRouter
) -> None:
    route = api.post("/v1/devices").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(TransportError, match="cannot reach"):
        client.nodes.create_edge_node({"name": "x"})
    assert route.call_count == 3  # first try + max_retries=2


def test_read_timeouts_on_writes_are_not_retried(
    client: ZedcloudClient, api: respx.MockRouter
) -> None:
    route = api.post("/v1/devices").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(TransportError):
        client.nodes.create_edge_node({"name": "x"})
    assert route.call_count == 1


def test_path_params_cannot_escape_their_segment(
    client: ZedcloudClient, api: respx.MockRouter
) -> None:
    route = api.route().mock(return_value=httpx.Response(200, json=DEVICE))
    client.nodes.get_edge_node_by_name("site-a/../../v1/users?x=#y")
    url = route.calls.last.request.url
    assert url.raw_path == b"/api/v1/devices/name/site-a%2F..%2F..%2Fv1%2Fusers%3Fx%3D%23y"


def test_empty_path_params_are_rejected(client: ZedcloudClient) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        client.nodes.get_edge_node("")


def test_multi_segment_params_keep_slashes_but_block_traversal(
    client: ZedcloudClient, api: respx.MockRouter
) -> None:
    route = api.route().mock(return_value=httpx.Response(200, json={}))
    client.k8s.proxy_kubernetes_get("c1", "api/v1/namespaces/default/pods")
    assert route.calls.last.request.url.path.endswith("/proxy/api/v1/namespaces/default/pods")
    with pytest.raises(ValueError, match=r"'\.\.'"):
        client.k8s.proxy_kubernetes_get("c1", "api/../../../v1/users")


def test_query_encoding(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices").mock(return_value=httpx.Response(200, json={}))
    client.nodes.query_edge_nodes(summary=True, order_by=["name", "-title"], page_size=5)
    params = route.calls.last.request.url.params
    assert params["summary"] == "true"
    assert params.get_list("next.orderBy") == ["name", "-title"]
    assert params["next.pageSize"] == "5"


def test_models_are_serialized_by_alias_without_nulls(
    client: ZedcloudClient, api: respx.MockRouter
) -> None:
    from zedcloud.models import UpdateEdgeNodeBody

    route = api.put("/v1/devices/id/1").mock(return_value=httpx.Response(200, json={}))
    client.nodes.update_edge_node("1", UpdateEdgeNodeBody(name="d", project_id="p"))
    assert json.loads(route.calls.last.request.content) == {"name": "d", "projectId": "p"}


def test_bytes_bodies_are_base64(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.put("/v1/artifacts/id/a/upload/chunked").mock(return_value=httpx.Response(200))
    client.storage.upload_artifact("a", b"\x00\x01chunk", content_range="bytes 0-6/7")
    sent = json.loads(route.calls.last.request.content)
    assert base64.b64decode(sent) == b"\x00\x01chunk"
    assert route.calls.last.request.headers["Content-Range"] == "bytes 0-6/7"


def test_zedcloud_error_details_are_surfaced(client: ZedcloudClient, api: respx.MockRouter) -> None:
    body = {
        "httpStatusCode": 409,
        "httpStatusMsg": "Conflict",
        "error": [
            {
                "ec": "zMsgErrorAlreadyExists",
                "details": "Device d already exists",
                "location": "name",
            }
        ],
    }
    api.post("/v1/devices").mock(return_value=httpx.Response(409, json=body))
    with pytest.raises(ConflictError) as info:
        client.nodes.create_edge_node({"name": "d"}, request_id="rid-1")
    err = info.value
    assert err.message == "Device d already exists"
    assert err.error_code == "zMsgErrorAlreadyExists"
    assert err.errors[0].location == "name"
    assert err.request_id == "rid-1"
    assert err.operation_id == "EdgeNodeConfiguration_CreateEdgeNode"
    assert "rid-1" in str(err) and "[409]" in str(err)


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, AuthError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (500, ServerError),
        (418, ApiError),
    ],
)
def test_status_mapping(
    client: ZedcloudClient, api: respx.MockRouter, status: int, exc: type
) -> None:
    api.delete("/v1/devices/id/1").mock(return_value=httpx.Response(status, text="nope"))
    with pytest.raises(exc) as info:
        client.nodes.delete_edge_node("1")
    assert info.value.message == "nope"


def test_non_json_responses_are_returned_as_text(
    client: ZedcloudClient, api: respx.MockRouter
) -> None:
    api.get("/v1/cluster/instances/kubernetes/c1/kubeconfig").mock(
        return_value=httpx.Response(
            200, text="apiVersion: v1\n", headers={"Content-Type": "application/yaml"}
        )
    )
    assert client.k8s.get_dashboard_kubeconfig("c1").startswith("apiVersion")


def test_empty_success_returns_none(client: ZedcloudClient, api: respx.MockRouter) -> None:
    api.put("/v1/devices/id/1/reboot").mock(return_value=httpx.Response(200))
    assert client.nodes.reboot("1") is None


def test_multipart_upload(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.put("/v1/apps/images/name/img/upload/file").mock(
        return_value=httpx.Response(200, json={})
    )
    client.storage.upload_image_file("img", ("disk.qcow2", b"QFI\xfb"))
    request = route.calls.last.request
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="imageFile"; filename="disk.qcow2"' in request.content
