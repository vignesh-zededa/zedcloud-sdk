"""``iter_*`` methods walk pages lazily and stop correctly."""

from __future__ import annotations

import httpx
import respx

from zedcloud import AsyncZedcloudClient, ZedcloudClient


def page(ids: list[int], total_pages: int | None = None) -> httpx.Response:
    cursor = {} if total_pages is None else {"totalPages": total_pages}
    return httpx.Response(200, json={"list": [{"id": str(i)} for i in ids], "next": cursor})


def test_walks_pages_until_total(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices").mock(
        side_effect=[page([1, 2], 3), page([3, 4], 3), page([5], 3)]
    )
    ids = [n.id for n in client.nodes.iter_edge_nodes(page_size=2, project_name="p")]
    assert ids == ["1", "2", "3", "4", "5"]
    assert [c.request.url.params["next.pageNum"] for c in route.calls] == ["1", "2", "3"]
    assert all(c.request.url.params["projectName"] == "p" for c in route.calls)


def test_a_capped_page_size_does_not_end_iteration(
    client: ZedcloudClient, api: respx.MockRouter
) -> None:
    # Server caps pages at 2 even though 100 were requested; totalPages is authoritative.
    api.get("/v1/devices").mock(side_effect=[page([1, 2], 2), page([3, 4], 2)])
    assert len(list(client.nodes.iter_edge_nodes())) == 4


def test_short_page_ends_iteration_without_total(
    client: ZedcloudClient, api: respx.MockRouter
) -> None:
    route = api.get("/v1/devices").mock(side_effect=[page([1, 2]), page([3])])
    assert len(list(client.nodes.iter_edge_nodes(page_size=2))) == 3
    assert route.call_count == 2


def test_repeated_page_stops_iteration(client: ZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/devices").mock(return_value=page([1, 2]))  # server ignores pageNum
    assert [n.id for n in client.nodes.iter_edge_nodes(page_size=2)] == ["1", "2"]


def test_max_items(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices").mock(side_effect=[page([1, 2], 5), page([3, 4], 5)])
    assert len(list(client.nodes.iter_edge_nodes(page_size=2, max_items=3))) == 3
    assert route.call_count == 2


def test_iteration_is_lazy(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices").mock(return_value=page([1], 1))
    iterator = client.nodes.iter_edge_nodes()
    assert route.call_count == 0
    next(iterator)
    assert route.call_count == 1


async def test_async_iteration(aclient: AsyncZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/devices").mock(side_effect=[page([1, 2], 2), page([3], 2)])
    ids = [n.id async for n in aclient.nodes.iter_edge_nodes(page_size=2)]
    assert ids == ["1", "2", "3"]
