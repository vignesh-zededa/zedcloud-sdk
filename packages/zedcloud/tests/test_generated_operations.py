"""Every generated operation must send the method and path its spec declares."""

from __future__ import annotations

import inspect
import re

import httpx
import pytest
import respx

from zedcloud import AsyncZedcloudClient, ZedcloudClient
from zedcloud.operations import Operation, all_operations

OPERATIONS = all_operations()


def _args(op: Operation) -> tuple[list[object], dict[str, object], str]:
    """Positional args for the method, and the path we expect on the wire."""
    args: list[object] = []
    expected = op.path
    for p in op.path_params:
        value = f"v-{p.python_name}"
        args.append(value)
        expected = expected.replace("{" + p.name + "}", value)
    args.extend(b"file-bytes" for p in op.params if p.location == "form")
    kwargs: dict[str, object] = {}
    if op.has_body:
        args.append({})
    for p in (*op.query_params, *op.header_params):
        if p.required:
            kwargs[p.python_name] = "x"
    return args, kwargs, expected


def test_registry_is_complete() -> None:
    assert len(OPERATIONS) == 470
    assert len({op.operation_id for op in OPERATIONS}) == 470
    assert {op.risk for op in OPERATIONS} == {"read", "write", "destructive"}


@pytest.mark.parametrize("op", OPERATIONS, ids=lambda op: op.operation_id)
def test_sync_operation_wire_format(
    op: Operation, client: ZedcloudClient, api: respx.MockRouter
) -> None:
    route = api.route().mock(return_value=httpx.Response(200, json={}))
    method = getattr(getattr(client, op.service), op.method_name)
    args, kwargs, expected = _args(op)
    method(*args, **kwargs)
    request = route.calls.last.request
    assert request.method == op.http_method
    assert request.url.path == "/api" + expected
    assert request.headers["Authorization"] == "Bearer tok"
    if any(p.location == "form" for p in op.params):
        assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert re.fullmatch(r"[0-9a-f]{32}", request.headers["X-Request-Id"])
    if op.service == "k8s":
        assert request.headers["X-API-KEY"] == "tok"
    else:
        assert "X-API-KEY" not in request.headers


@pytest.mark.parametrize("op", OPERATIONS[::25], ids=lambda op: op.operation_id)
async def test_async_operation_wire_format(
    op: Operation, aclient: AsyncZedcloudClient, api: respx.MockRouter
) -> None:
    route = api.route().mock(return_value=httpx.Response(200, json={}))
    method = getattr(getattr(aclient, op.service), op.method_name)
    assert inspect.iscoroutinefunction(method)
    args, kwargs, expected = _args(op)
    await method(*args, **kwargs)
    assert route.calls.last.request.url.path == "/api" + expected


def test_sync_and_async_surfaces_match(
    client: ZedcloudClient, aclient: AsyncZedcloudClient
) -> None:
    for ns in {op.service for op in OPERATIONS}:
        sync_names = {n for n in dir(getattr(client, ns)) if not n.startswith("_")}
        async_names = {n for n in dir(getattr(aclient, ns)) if not n.startswith("_")}
        assert sync_names == async_names, ns


def test_every_method_is_documented(client: ZedcloudClient) -> None:
    for op in OPERATIONS:
        doc = getattr(getattr(client, op.service), op.method_name).__doc__ or ""
        assert op.operation_id in doc and op.path in doc


def test_optional_params_are_keyword_only(client: ZedcloudClient) -> None:
    sig = inspect.signature(client.nodes.query_edge_nodes)
    assert all(p.kind is p.KEYWORD_ONLY for p in sig.parameters.values())
