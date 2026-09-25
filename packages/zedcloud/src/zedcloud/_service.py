"""Base classes for the generated service namespaces."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from functools import cache
from typing import IO, Any

from zedcloud._transport import AsyncTransport, SyncTransport

FileContent = bytes | IO[bytes] | tuple[str, bytes | IO[bytes]]
"""A file to upload: raw bytes, an open binary file, or ``(filename, bytes_or_file)``."""

# Hard stop for servers that ignore the page cursor.
MAX_PAGES = 10_000


@cache
def _accepts(func: Callable[..., Any]) -> frozenset[str]:
    return frozenset(inspect.signature(func).parameters)


def _page_kwargs(
    fetch: Callable[..., Any], page_size: int, page_num: int, token: str | None
) -> dict[str, Any]:
    accepted = _accepts(getattr(fetch, "__func__", fetch))
    kwargs: dict[str, Any] = {"page_size": page_size}
    if "page_num" in accepted:
        kwargs["page_num"] = page_num
    if token and "page_token" in accepted:
        kwargs["page_token"] = token
    return kwargs


def _has_more(page: Any, count: int, page_num: int, page_size: int) -> tuple[bool, str | None]:
    """Whether another page follows, and the server's continuation token."""
    cursor = getattr(page, "next", None)
    total = getattr(cursor, "total_pages", None) if cursor is not None else None
    token = getattr(cursor, "page_token", None) if cursor is not None else None
    if total:
        return page_num < int(total), token
    # No page count: a short page means we reached the end.
    return count >= page_size, token


def _identity(item: Any) -> Any:
    return getattr(item, "id", None) or getattr(item, "name", None) or repr(item)


class BaseService:
    """A group of operations sharing one synchronous transport."""

    _security = "bearer"

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def _request(self, method: str, template: str, **kwargs: Any) -> Any:
        return self._transport.request(
            method, template, api_key_auth=self._security == "api_key", **kwargs
        )

    def _paginate(
        self,
        fetch: Callable[..., Any],
        *,
        page_size: int,
        max_items: int | None,
        **filters: Any,
    ) -> Iterator[Any]:
        page_num, token, previous_first, yielded = 1, None, None, 0
        while page_num <= MAX_PAGES:
            page = fetch(**filters, **_page_kwargs(fetch, page_size, page_num, token))
            items = list(getattr(page, "list", None) or [])
            first = _identity(items[0]) if items else None
            if not items or first == previous_first:
                return  # finished, or the server ignored the cursor and repeated a page
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            more, token = _has_more(page, len(items), page_num, page_size)
            if not more:
                return
            previous_first = first
            page_num += 1


class AsyncBaseService:
    """A group of operations sharing one asynchronous transport."""

    _security = "bearer"

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def _request(self, method: str, template: str, **kwargs: Any) -> Any:
        return await self._transport.request(
            method, template, api_key_auth=self._security == "api_key", **kwargs
        )

    async def _paginate(
        self,
        fetch: Callable[..., Awaitable[Any]],
        *,
        page_size: int,
        max_items: int | None,
        **filters: Any,
    ) -> AsyncIterator[Any]:
        page_num, token, previous_first, yielded = 1, None, None, 0
        while page_num <= MAX_PAGES:
            page = await fetch(**filters, **_page_kwargs(fetch, page_size, page_num, token))
            items = list(getattr(page, "list", None) or [])
            first = _identity(items[0]) if items else None
            if not items or first == previous_first:
                return  # finished, or the server ignored the cursor and repeated a page
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            more, token = _has_more(page, len(items), page_num, page_size)
            if not more:
                return
            previous_first = first
            page_num += 1
