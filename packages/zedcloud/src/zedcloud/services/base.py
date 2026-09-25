"""Service base class shared by generated API namespaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from urllib.parse import quote

from pydantic import BaseModel

from zedcloud.http import HttpTransport

T = TypeVar("T", bound=BaseModel)


def quote_path_param(value: object) -> str:
    """Percent-encode a path parameter so it stays within a single segment."""
    return quote(str(value), safe="")


class BaseService:
    """Namespace bound to a shared :class:`~zedcloud.http.HttpTransport`."""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        response_model: type[T] | None = None,
    ) -> T | Any:
        return self._transport.request(
            method,
            path,
            params=params,
            json_body=json_body,
            headers=headers,
            response_model=response_model,
        )
