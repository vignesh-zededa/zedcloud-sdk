"""HTTP transport with retries for Zedcloud APIs."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, MutableMapping
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from zedcloud.errors import ApiError, error_for_status

T = TypeVar("T", bound=BaseModel)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class HttpTransport:
    """Thin httpx wrapper with auth headers, retries, and typed decoding."""

    def __init__(
        self,
        *,
        api_root: str,
        default_headers: Mapping[str, str],
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_root = api_root.rstrip("/")
        self._default_headers = dict(default_headers)
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        response_model: type[T] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> T | Any:
        """Perform an HTTP request relative to the OpenAPI ``/api`` root.

        ``path`` must be the swagger path (e.g. ``/v1/apps``), not including
        ``/api``.
        """
        url = f"{self.api_root}{path if path.startswith('/') else '/' + path}"
        merged: MutableMapping[str, str] = dict(self._default_headers)
        if extra_headers:
            merged.update({k: v for k, v in extra_headers.items() if v is not None})
        if headers:
            merged.update({k: v for k, v in headers.items() if v is not None})

        body: Any = json_body
        if isinstance(json_body, BaseModel):
            body = json_body.model_dump(mode="json", by_alias=True, exclude_none=True)

        query = _normalize_params(params)
        attempt = 0
        while True:
            response = self._client.request(
                method.upper(),
                url,
                params=query,
                json=body,
                headers=merged,
                timeout=self.timeout,
            )
            if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    delay = self.retry_backoff * (2**attempt)
                time.sleep(delay)
                attempt += 1
                continue
            return self._decode(
                response, method=method.upper(), url=url, response_model=response_model
            )

    def _decode(
        self,
        response: httpx.Response,
        *,
        method: str,
        url: str,
        response_model: type[T] | None,
    ) -> T | Any:
        request_id = response.headers.get("X-Request-Id") or response.headers.get("x-request-id")
        if response.status_code >= 400:
            parsed = _safe_json(response)
            message = _error_message(parsed, response)
            raise error_for_status(
                response.status_code,
                message,
                method=method,
                url=str(response.request.url) if response.request else url,
                body=parsed,
                request_id=request_id,
            )
        if response.status_code == 204 or not response.content:
            if response_model is not None:
                return response_model.model_validate({})
            return None
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ApiError(
                f"Non-JSON response ({response.status_code})",
                status_code=response.status_code,
                method=method,
                url=str(response.request.url) if response.request else url,
                body=response.text,
                request_id=request_id,
            ) from exc
        if response_model is None:
            return data
        return response_model.model_validate(data)


def _normalize_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    out: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            out[key] = list(value)
        else:
            out[key] = value
    return out or None


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def _error_message(parsed: Any, response: httpx.Response) -> str:
    if isinstance(parsed, dict):
        for key in ("message", "error", "errorMessage", "detail", "title"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value
        # google.rpc.Status style
        if isinstance(parsed.get("message"), str):
            return parsed["message"]
    if isinstance(parsed, str) and parsed.strip():
        return parsed.strip()[:500]
    return f"HTTP {response.status_code}"
