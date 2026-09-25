"""Exceptions raised by the Zedcloud SDK.

Hierarchy::

    ZedcloudError
    ├── ConfigError                 bad/missing configuration or profile
    ├── TransportError              network failure, no HTTP response
    ├── WaitTimeoutError            a waiter gave up
    └── ApiError                    the API returned an error status
        ├── BadRequestError         400
        ├── AuthError               401 / 403
        │   ├── AuthenticationError 401 (and failed logins)
        │   └── PermissionDeniedError 403
        ├── NotFoundError           404
        ├── ConflictError           409
        ├── PreconditionFailedError 412
        ├── RateLimitError          429
        └── ServerError             5xx
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ZedcloudError(Exception):
    """Base class for every error raised by this SDK."""


class ConfigError(ZedcloudError, ValueError):
    """Configuration is missing or invalid (unknown profile, no credentials, …)."""


class TransportError(ZedcloudError):
    """The request failed before an HTTP response was received."""

    def __init__(self, message: str, *, method: str | None = None, url: str | None = None):
        super().__init__(message)
        self.method = method
        self.url = url


class WaitTimeoutError(ZedcloudError, TimeoutError):
    """A waiter did not observe the expected state before its deadline."""

    def __init__(self, message: str, *, last: Any = None):
        super().__init__(message)
        self.last = last


@dataclass(frozen=True)
class ErrorDetail:
    """One entry of Zedcloud's ``error`` array."""

    code: str | None
    details: str | None
    location: str | None = None


class ApiError(ZedcloudError):
    """The Zedcloud API answered with an error status.

    Attributes:
        status_code: HTTP status.
        method / url: The failed request.
        request_id: ``X-Request-Id`` sent with the request; quote it to ZEDEDA support.
        error_code: First Zedcloud error code (e.g. ``zMsgErrorAlreadyExists``), if any.
        errors: Every error entry the API returned.
        body: The decoded response body (dict, or text if not JSON).
        operation_id: The OpenAPI operation that failed, when known.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        method: str | None = None,
        url: str | None = None,
        body: Any = None,
        request_id: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.method = method
        self.url = url
        self.body = body
        self.request_id = request_id
        self.operation_id = operation_id
        self.errors = parse_error_details(body)
        self.error_code = self.errors[0].code if self.errors else None

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.insert(0, f"[{self.status_code}]")
        if self.method and self.url:
            parts.append(f"({self.method} {self.url})")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " ".join(parts)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, "
            f"error_code={self.error_code!r}, message={self.message!r}, "
            f"request_id={self.request_id!r})"
        )


class BadRequestError(ApiError):
    """400 — the request was malformed or failed validation."""


class AuthError(ApiError):
    """401 / 403 — missing, expired, or insufficient credentials."""


class AuthenticationError(AuthError):
    """401 — credentials missing, invalid, or expired; or a login was rejected."""


class PermissionDeniedError(AuthError):
    """403 — authenticated, but the user's role does not allow this operation."""


class NotFoundError(ApiError):
    """404 — the resource does not exist (or is not visible to this user)."""


class ConflictError(ApiError):
    """409 — conflicts with existing state, e.g. a duplicate name."""


class PreconditionFailedError(ApiError):
    """412 — a precondition such as an object revision did not match."""


class RateLimitError(ApiError):
    """429 — rate limited, after retries were exhausted."""


class ServerError(ApiError):
    """5xx — Zedcloud failed to process the request."""


_STATUS_CLASSES: dict[int, type[ApiError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    412: PreconditionFailedError,
    429: RateLimitError,
}


def error_class_for_status(status_code: int) -> type[ApiError]:
    if status_code in _STATUS_CLASSES:
        return _STATUS_CLASSES[status_code]
    return ServerError if status_code >= 500 else ApiError


def error_for_status(status_code: int, message: str, **kwargs: Any) -> ApiError:
    """Build the :class:`ApiError` subclass matching ``status_code``."""
    return error_class_for_status(status_code)(message, status_code=status_code, **kwargs)


def parse_error_details(body: Any) -> list[ErrorDetail]:
    """Extract error entries from Zedcloud (``error``) or gRPC (``details``) bodies."""
    if not isinstance(body, dict):
        return []
    entries = body.get("error")
    if isinstance(entries, dict):
        entries = [entries]
    out: list[ErrorDetail] = []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                code = entry.get("ec")
                out.append(
                    ErrorDetail(
                        code=str(code) if code is not None else None,
                        details=entry.get("details"),
                        location=entry.get("location") or None,
                    )
                )
    return out


def error_message(body: Any, status_code: int) -> str:
    """Pick the most useful human-readable message from an error body."""
    details = [d.details for d in parse_error_details(body) if d.details]
    if details:
        return "; ".join(details)
    if isinstance(body, dict):
        for key in ("message", "httpStatusMsg", "error", "detail", "title"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(body, str) and body.strip():
        return body.strip()[:500]
    return f"HTTP {status_code}"
