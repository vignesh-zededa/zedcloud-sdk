"""Pytest markers and credential detection for Zedcloud suites."""

from __future__ import annotations

from typing import Any

import pytest

from zedcloud import ConfigError
from zedcloud.config import ZedcloudConfig, resolve_config

smoke = pytest.mark.smoke
integration = pytest.mark.integration
needs_cloud = pytest.mark.needs_cloud


def register_markers(config: Any) -> None:
    config.addinivalue_line("markers", "smoke: read-only checks against a live tenant")
    config.addinivalue_line(
        "markers", "integration: creates or modifies resources; needs allow_writes on the profile"
    )
    config.addinivalue_line("markers", "needs_cloud: requires credentials for a live tenant")


def try_resolve(profile: str | None = None) -> ZedcloudConfig | None:
    """Resolve tenant settings, or ``None`` if none are configured."""
    try:
        return resolve_config(profile=profile)
    except ConfigError:
        return None


def credentials_available(profile: str | None = None) -> bool:
    return try_resolve(profile) is not None
