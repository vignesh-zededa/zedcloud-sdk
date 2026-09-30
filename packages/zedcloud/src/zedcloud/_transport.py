"""HTTP transports (sync and async) shared by every service.

Retry policy:

* connection failures (the request never reached the server) — any method;
* 429 (the server refused before processing) — any method, honouring ``Retry-After``;
* 500/502/503/504 — only idempotent methods (GET/HEAD/OPTIONS). A 5xx on a
  write is ambiguous; replaying it risks a duplicate create or a second
  reboot, so the error is surfaced instead.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import time
import uuid
from collections.abc import Collection, Mapping
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from zedcloud._version import __version__
from zedcloud.auth import API_KEY_EXTENSION, ZedcloudAuth
from zedcloud.config import ZedcloudConfig
from zedcloud.errors import ApiError, TransportError, error_for_status, error_message

logger = logging.getLogger("zedcloud")

RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_BACKOFF = 30.0
USER_AGENT = f"zedcloud-python/{__version__}"


def should_retry_status(method: str, status_code: int) -> bool:
    if status_code == 429:
        return True
    return status_code in RETRYABLE_STATUS and method in IDEMPOTENT_METHODS


def render_path(
    template: str, values: Mapping[str, Any] | None, multi_segment: Collection[str] = ()
) -> str:
    """Substitute ``{name}`` placeholders with percent-encoded values.

    Values are encoded so they cannot leave their path segment. Parameters in
    ``multi_segment`` (e.g. the Kubernetes proxy ``path``) keep ``/`` but may
    not contain ``.`` or ``..`` segments.
    """
    path = template
    for name, value in (values or {}).items():
        if value is None or value == "":
            raise ValueError(f"path parameter {name!r} must not be empty")
        text = str(value.value if hasattr(value, "value") else value)
        if name in multi_segment:
            segments = text.strip("/").split("/")
            if any(seg in {".", ".."} for seg in segments):
                raise ValueError(f"path parameter {name!r} may not contain '.' or '..' segments")
            encoded = "/".join(quote(seg, safe="") for seg in segments)
        else:
            encoded = quote(text, safe="")
        path = path.replace("{" + name + "}", encoded)
    return path


def encode_query(query: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """Drop ``None`` values; repeat keys for sequences; lower-case booleans."""
    out: list[tuple[str, str]] = []
    for key, value in (query or {}).items():
        if value is None:
            continue
        values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
        for item in values:
            if isinstance(item, bool):
                out.append((key, "true" if item else "false"))
            elif hasattr(item, "value"):  # enums
                out.append((key, str(item.value)))
            else:
                out.append((key, str(item)))
    return out


def encode_body(body: Any) -> Any:
    if body is None:
        return None
    if isinstance(body, BaseModel):
        return body.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(body, (bytes, bytearray, memoryview)):
        # ``format: byte`` bodies (chunked uploads) travel as a base64 JSON string.
        return base64.b64encode(bytes(body)).decode("ascii")
    return body


class _TransportBase:
    def __init__(self, config: ZedcloudConfig) -> None:
        self.config = config
        self.auth = ZedcloudAuth(
            config.credentials, api_root=config.api_root, api_key=config.api_key
        )
        self._headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            **config.extra_headers,
        }

    def _build(
        self,
        client: httpx.Client | httpx.AsyncClient,
        method: str,
        template: str,
        *,
        path: Mapping[str, Any] | None,
        multi_segment: Collection[str],
        query: Mapping[str, Any] | None,
        headers: Mapping[str, Any] | None,
        body: Any,
        files: Mapping[str, Any] | None,
        request_id: str,
        api_key_auth: bool,
    ) -> httpx.Request:
        url = self.config.api_root + render_path(template, path, multi_segment)
        merged = dict(self._headers)
        merged.update({k: str(v) for k, v in (headers or {}).items() if v is not None})
        merged["X-Request-Id"] = request_id
        payload = encode_body(body)
        return client.build_request(
            method,
            url,
            params=encode_query(query),
            json=payload if not files else None,
            files={k: v for k, v in files.items() if v is not None} if files else None,
            headers=merged,
            timeout=self.config.timeout,
            extensions={API_KEY_EXTENSION: api_key_auth},
        )

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return min(float(retry_after), MAX_BACKOFF)
        base = self.config.retry_backoff * (2**attempt)
        return min(base, MAX_BACKOFF) * (0.5 + random.random() / 2)

    def _decode(
        self,
        response: httpx.Response,
        *,
        response_model: type[BaseModel] | None,
        request_id: str,
        operation_id: str | None,
        elapsed: float,
    ) -> Any:
        request = response.request
        logger.debug(
            "%s %s -> %s in %.0fms (request_id=%s)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed * 1000,
            request_id,
        )
        if response.status_code >= 400:
            body = _safe_body(response)
            raise error_for_status(
                response.status_code,
                error_message(body, response.status_code),
                method=request.method,
                url=str(request.url.copy_with(query=None)),
                body=body,
                request_id=request_id,
                operation_id=operation_id,
            )
        if response.status_code == 204 or not response.content:
            return None
        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type and not response.content.lstrip().startswith((b"{", b"[")):
            return response.text
        try:
            data = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return response.text
        if response_model is None or not isinstance(data, dict):
            return data
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise ApiError(
                f"could not decode {response_model.__name__} response: {exc}",
                status_code=response.status_code,
                method=request.method,
                url=str(request.url),
                body=data,
                request_id=request_id,
                operation_id=operation_id,
            ) from exc


class SyncTransport(_TransportBase):
    """Blocking transport on ``httpx.Client``."""

    def __init__(self, config: ZedcloudConfig, client: httpx.Client | None = None) -> None:
        super().__init__(config)
        self._owns_client = client is None
        self._client = client or httpx.Client(verify=config.verify, timeout=config.timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def request(
        self,
        method: str,
        template: str,
        *,
        path: Mapping[str, Any] | None = None,
        multi_segment: Collection[str] = (),
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        body: Any = None,
        files: Mapping[str, Any] | None = None,
        response_model: type[BaseModel] | None = None,
        request_id: str | None = None,
        operation_id: str | None = None,
        api_key_auth: bool = False,
    ) -> Any:
        method = method.upper()
        request_id = request_id or uuid.uuid4().hex
        request = self._build(
            self._client,
            method,
            template,
            path=path,
            multi_segment=multi_segment,
            query=query,
            headers=headers,
            body=body,
            files=files,
            request_id=request_id,
            api_key_auth=api_key_auth,
        )
        attempt = 0
        while True:
            started = time.monotonic()
            try:
                response = self._client.send(request, auth=self.auth)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt >= self.config.max_retries:
                    raise TransportError(
                        f"cannot reach {request.url.host}: {exc}",
                        method=method,
                        url=str(request.url),
                    ) from exc
                time.sleep(self._delay(attempt, None))
                attempt += 1
                continue
            except httpx.TransportError as exc:
                raise TransportError(
                    f"{method} {request.url.path} failed: {exc}",
                    method=method,
                    url=str(request.url),
                ) from exc
            if (
                should_retry_status(method, response.status_code)
                and attempt < self.config.max_retries
            ):
                delay = self._delay(attempt, response)
                logger.info(
                    "%s %s -> %s, retrying in %.1fs",
                    method,
                    request.url.path,
                    response.status_code,
                    delay,
                )
                response.close()
                time.sleep(delay)
                attempt += 1
                continue
            return self._decode(
                response,
                response_model=response_model,
                request_id=request_id,
                operation_id=operation_id,
                elapsed=time.monotonic() - started,
            )


class AsyncTransport(_TransportBase):
    """Non-blocking transport on ``httpx.AsyncClient``."""

    def __init__(self, config: ZedcloudConfig, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(verify=config.verify, timeout=config.timeout)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def request(
        self,
        method: str,
        template: str,
        *,
        path: Mapping[str, Any] | None = None,
        multi_segment: Collection[str] = (),
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        body: Any = None,
        files: Mapping[str, Any] | None = None,
        response_model: type[BaseModel] | None = None,
        request_id: str | None = None,
        operation_id: str | None = None,
        api_key_auth: bool = False,
    ) -> Any:
        method = method.upper()
        request_id = request_id or uuid.uuid4().hex
        request = self._build(
            self._client,
            method,
            template,
            path=path,
            multi_segment=multi_segment,
            query=query,
            headers=headers,
            body=body,
            files=files,
            request_id=request_id,
            api_key_auth=api_key_auth,
        )
        attempt = 0
        while True:
            started = time.monotonic()
            try:
                response = await self._client.send(request, auth=self.auth)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt >= self.config.max_retries:
                    raise TransportError(
                        f"cannot reach {request.url.host}: {exc}",
                        method=method,
                        url=str(request.url),
                    ) from exc
                await asyncio.sleep(self._delay(attempt, None))
                attempt += 1
                continue
            except httpx.TransportError as exc:
                raise TransportError(
                    f"{method} {request.url.path} failed: {exc}",
                    method=method,
                    url=str(request.url),
                ) from exc
            if (
                should_retry_status(method, response.status_code)
                and attempt < self.config.max_retries
            ):
                delay = self._delay(attempt, response)
                logger.info(
                    "%s %s -> %s, retrying in %.1fs",
                    method,
                    request.url.path,
                    response.status_code,
                    delay,
                )
                await response.aclose()
                await asyncio.sleep(delay)
                attempt += 1
                continue
            return self._decode(
                response,
                response_model=response_model,
                request_id=request_id,
                operation_id=operation_id,
                elapsed=time.monotonic() - started,
            )


def _safe_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return response.text
