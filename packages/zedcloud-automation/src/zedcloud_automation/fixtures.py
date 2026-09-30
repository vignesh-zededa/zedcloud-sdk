"""Pytest fixtures yielding authenticated Zedcloud clients.

Select the tenant with ``--zedcloud-profile NAME`` (or ``ZEDCLOUD_PROFILE``,
or ``ZEDCLOUD_*`` variables). Tests needing a tenant are skipped when none is
configured. Tests marked ``integration`` are also skipped unless the profile
sets ``allow_writes = true``, so a suite cannot modify a read-only tenant.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from zedcloud import ZedcloudClient
from zedcloud.config import ZedcloudConfig
from zedcloud_automation.markers import try_resolve
from zedcloud_automation.resources import ResourceTracker


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--zedcloud-profile",
        default=None,
        help="Zedcloud profile to run live tests against (see ~/.config/zedcloud/config.toml)",
    )


@pytest.fixture(scope="session")
def zedcloud_config(request: pytest.FixtureRequest) -> ZedcloudConfig:
    """Resolved tenant settings; skips the test when no tenant is configured."""
    config = try_resolve(request.config.getoption("--zedcloud-profile"))
    if config is None:
        pytest.skip("no Zedcloud tenant configured (use --zedcloud-profile or ZEDCLOUD_* vars)")
    return config


@pytest.fixture(scope="session")
def zedcloud_client(zedcloud_config: ZedcloudConfig) -> Iterator[ZedcloudClient]:
    """Session-scoped authenticated client."""
    with ZedcloudClient(config=zedcloud_config) as client:
        yield client


@pytest.fixture(autouse=True)
def _guard_integration_writes(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("integration") is None:
        return
    config = try_resolve(request.config.getoption("--zedcloud-profile"))
    if config is not None and not config.allow_writes:
        pytest.skip(f"profile {config.label!r} does not set allow_writes = true")


@pytest.fixture
def resource_tracker(zedcloud_client: ZedcloudClient) -> Iterator[ResourceTracker]:
    """Track created resources and delete them (in reverse order) after the test."""
    tracker = ResourceTracker(zedcloud_client)
    yield tracker
    tracker.cleanup()


__all__ = [
    "_guard_integration_writes",
    "pytest_addoption",
    "resource_tracker",
    "zedcloud_client",
    "zedcloud_config",
]
