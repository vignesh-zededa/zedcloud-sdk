"""Pytest plugin registration for zedcloud-automation."""

from __future__ import annotations

from typing import Any

from zedcloud_automation.fixtures import *  # noqa: F403
from zedcloud_automation.markers import register_markers


def pytest_configure(config: Any) -> None:
    register_markers(config)
