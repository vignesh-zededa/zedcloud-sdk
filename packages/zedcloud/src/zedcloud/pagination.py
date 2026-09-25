"""Pagination helpers for Zedcloud list endpoints.

Most list operations accept ``next.pageToken`` / ``next.pageNum`` /
``next.pageSize`` query parameters and return a ``next`` :class:`Cursor`
alongside a ``list`` array.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, TypeVar

T = TypeVar("T")


def iter_pages(
    fetch_page: Callable[..., Any],
    *,
    page_size: int | float = 50,
    max_pages: int | None = None,
    item_attr: str = "list",
    cursor_attr: str = "next",
    **filters: Any,
) -> Iterator[Any]:
    """Yield items across pages for a Zedcloud list/query callable.

    ``fetch_page`` must accept ``next_page_token``, ``next_page_num``, and
    ``next_page_size`` keyword arguments (as generated service methods do).
    """
    page_token: str | None = None
    page_num = 1
    pages = 0
    while True:
        response = fetch_page(
            next_page_token=page_token,
            next_page_num=page_num,
            next_page_size=page_size,
            **filters,
        )
        items = _get_attr(response, item_attr) or []
        yield from items
        pages += 1
        if max_pages is not None and pages >= max_pages:
            break
        cursor = _get_attr(response, cursor_attr)
        next_token = _get_attr(cursor, "page_token") if cursor is not None else None
        if not next_token and not items:
            break
        if not next_token:
            # Fall back to page-number walking when token is absent.
            total_pages = _get_attr(cursor, "total_pages") if cursor is not None else None
            if total_pages is not None and page_num >= int(total_pages):
                break
            if len(items) < page_size:
                break
            page_num += 1
            page_token = None
            continue
        page_token = str(next_token)
        page_num += 1


def collect_all(
    fetch_page: Callable[..., Any],
    *,
    page_size: int | float = 50,
    max_pages: int | None = None,
    item_attr: str = "list",
    cursor_attr: str = "next",
    **filters: Any,
) -> list[Any]:
    """Materialize all pages from :func:`iter_pages` into a list."""
    return list(
        iter_pages(
            fetch_page,
            page_size=page_size,
            max_pages=max_pages,
            item_attr=item_attr,
            cursor_attr=cursor_attr,
            **filters,
        )
    )


def _get_attr(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        if name in obj:
            return obj[name]
        camel = _to_camel(name)
        return obj.get(camel)
    # Generated models rename reserved field ``list`` → ``list_`` (alias ``list``).
    for candidate in (name, f"{name}_" if not name.endswith("_") else name.rstrip("_")):
        if hasattr(obj, candidate):
            return getattr(obj, candidate)
    return None


def _to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])
