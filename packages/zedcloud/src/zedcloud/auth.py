"""Authentication helpers for Zedcloud APIs."""

from __future__ import annotations

from zedcloud.config import ZedcloudConfig


def bearer_headers(config: ZedcloudConfig) -> dict[str, str]:
    """Headers for BearerToken-secured services (majority of Zedcloud APIs)."""
    return {
        "Authorization": f"Bearer {config.token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def api_key_headers(config: ZedcloudConfig) -> dict[str, str]:
    """Headers for ApiKeyAuth-secured services (Kubernetes / ZKS).

    Sends both ``X-API-KEY`` and ``Authorization: Bearer`` so callers can use
    either credential style against the same client instance.
    """
    headers = bearer_headers(config)
    headers["X-API-KEY"] = config.effective_api_key
    return headers
