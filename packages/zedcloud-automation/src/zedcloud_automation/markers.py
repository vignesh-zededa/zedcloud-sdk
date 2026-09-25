"""Pytest markers for Zedcloud automation suites."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, TypeVar

import pytest

F = TypeVar("F", bound=Callable[..., Any])

smoke = pytest.mark.smoke
integration = pytest.mark.integration
needs_cloud = pytest.mark.needs_cloud


def register_markers(config: Any) -> None:
    config.addinivalue_line("markers", "smoke: read-only smoke checks")
    config.addinivalue_line("markers", "integration: may create or modify resources")
    config.addinivalue_line(
        "markers",
        "needs_cloud: requires ZEDCLOUD_BASE_URL and ZEDCLOUD_TOKEN",
    )


def credentials_available() -> bool:
    return bool(os.environ.get("ZEDCLOUD_BASE_URL") and os.environ.get("ZEDCLOUD_TOKEN"))


def skip_without_credentials() -> None:
    if not credentials_available():
        pytest.skip("ZEDCLOUD_BASE_URL and ZEDCLOUD_TOKEN are required")
