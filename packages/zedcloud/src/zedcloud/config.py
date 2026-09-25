"""Configuration for the Zedcloud SDK."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ZedcloudConfig:
    """Connection settings for a Zedcloud tenant.

    Attributes:
        base_url: Tenant control-plane URL, e.g. ``https://zedcontrol.zededa.net``.
            Paths are rooted at ``/api`` (OpenAPI ``basePath``).
        token: Session / API token used for ``Authorization: Bearer …``.
        api_key: Optional value for ``X-API-KEY`` (Kubernetes / ZKS service).
            Defaults to ``token`` when unset.
        timeout: Default request timeout in seconds.
        max_retries: Retries for 429 / 5xx responses.
        retry_backoff: Initial backoff seconds (doubles each retry).
    """

    base_url: str
    token: str
    api_key: str | None = None
    timeout: float = 30.0
    max_retries: int = 3
    retry_backoff: float = 0.5

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        token: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> ZedcloudConfig:
        """Build config from explicit args with ``ZEDCLOUD_*`` env fallbacks."""
        resolved_base = base_url or os.environ.get("ZEDCLOUD_BASE_URL")
        resolved_token = token or os.environ.get("ZEDCLOUD_TOKEN")
        if not resolved_base:
            msg = "ZEDCLOUD_BASE_URL is required (arg or environment)"
            raise ValueError(msg)
        if not resolved_token:
            msg = "ZEDCLOUD_TOKEN is required (arg or environment)"
            raise ValueError(msg)
        resolved_api_key = api_key if api_key is not None else os.environ.get("ZEDCLOUD_API_KEY")
        return cls(
            base_url=resolved_base.rstrip("/"),
            token=resolved_token,
            api_key=resolved_api_key,
            timeout=timeout
            if timeout is not None
            else float(os.environ.get("ZEDCLOUD_TIMEOUT", "30")),
            max_retries=(
                max_retries
                if max_retries is not None
                else int(os.environ.get("ZEDCLOUD_MAX_RETRIES", "3"))
            ),
        )

    @property
    def effective_api_key(self) -> str:
        """API key for ``X-API-KEY`` header (falls back to bearer token)."""
        return self.api_key or self.token

    @property
    def api_root(self) -> str:
        """HTTP origin + OpenAPI base path (``/api``)."""
        base = self.base_url.rstrip("/")
        if base.endswith("/api"):
            return base
        return f"{base}/api"
