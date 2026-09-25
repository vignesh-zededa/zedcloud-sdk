"""Structured API errors raised by the Zedcloud SDK."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Base error for unsuccessful Zedcloud HTTP responses."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        method: str | None = None,
        url: str | None = None,
        body: Any = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.url = url
        self.body = body
        self.request_id = request_id

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, "
            f"method={self.method!r}, url={self.url!r}, message={str(self)!r})"
        )


class AuthError(ApiError):
    """401 / 403 — missing or insufficient credentials."""


class NotFoundError(ApiError):
    """404 — resource not found."""


class ConflictError(ApiError):
    """409 — resource conflict."""


class RateLimitError(ApiError):
    """429 — rate limited (retries may already have been exhausted)."""


class ServerError(ApiError):
    """5xx — upstream server error after retries."""


def error_for_status(
    status_code: int,
    message: str,
    *,
    method: str | None = None,
    url: str | None = None,
    body: Any = None,
    request_id: str | None = None,
) -> ApiError:
    """Map an HTTP status code to a concrete :class:`ApiError` subclass."""
    kwargs: dict[str, Any] = {
        "status_code": status_code,
        "method": method,
        "url": url,
        "body": body,
        "request_id": request_id,
    }
    if status_code in {401, 403}:
        return AuthError(message, **kwargs)
    if status_code == 404:
        return NotFoundError(message, **kwargs)
    if status_code == 409:
        return ConflictError(message, **kwargs)
    if status_code == 429:
        return RateLimitError(message, **kwargs)
    if status_code >= 500:
        return ServerError(message, **kwargs)
    return ApiError(message, **kwargs)
