"""Pytest fixtures yielding authenticated Zedcloud clients."""

from __future__ import annotations

import pytest

from zedcloud import ZedcloudClient
from zedcloud_automation.markers import credentials_available, skip_without_credentials
from zedcloud_automation.resources import ResourceTracker


@pytest.fixture(scope="session")
def zedcloud_credentials_present() -> bool:
    return credentials_available()


@pytest.fixture(scope="session")
def zedcloud_client(zedcloud_credentials_present: bool):
    """Session-scoped authenticated client; skips when credentials are missing."""
    if not zedcloud_credentials_present:
        skip_without_credentials()
    client = ZedcloudClient.from_env()
    yield client
    client.close()


@pytest.fixture
def resource_tracker(zedcloud_client: ZedcloudClient):
    """Track created resources and delete them after the test."""
    tracker = ResourceTracker(zedcloud_client)
    yield tracker
    tracker.cleanup()


__all__ = [
    "resource_tracker",
    "zedcloud_client",
    "zedcloud_credentials_present",
]
