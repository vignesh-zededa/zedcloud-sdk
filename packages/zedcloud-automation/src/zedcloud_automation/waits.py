"""Polling helpers for eventually-consistent Zedcloud state."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def wait_until(
    predicate: Callable[[], T | None | bool],
    *,
    timeout: float = 60.0,
    interval: float = 2.0,
    message: str = "condition not met",
) -> T:
    """Poll ``predicate`` until it returns a truthy value or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    last: T | None | bool = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last  # type: ignore[return-value]
        time.sleep(interval)
    raise TimeoutError(f"{message} (last={last!r})")
