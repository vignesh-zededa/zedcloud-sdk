"""Poll until Zedcloud reaches a desired state.

Most changes in Zedcloud are eventually consistent: an API call returns once
the controller accepts it, and the edge node converges later. These helpers
poll a fetch function until a predicate holds.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Collection
from typing import Any, TypeVar

from zedcloud.errors import WaitFailedError, WaitTimeoutError

T = TypeVar("T")
logger = logging.getLogger("zedcloud.waiters")


def wait_until(
    fetch: Callable[[], T],
    done: Callable[[T], bool],
    *,
    failed: Callable[[T], bool] | None = None,
    timeout: float = 300.0,
    interval: float = 5.0,
    description: str = "condition",
) -> T:
    """Call ``fetch`` every ``interval`` seconds until ``done(result)`` holds.

    Raises:
        WaitFailedError: ``failed(result)`` held first.
        WaitTimeoutError: ``timeout`` elapsed; ``.last`` holds the last result.
    """
    deadline = time.monotonic() + timeout
    while True:
        last = fetch()
        if done(last):
            return last
        if failed is not None and failed(last):
            raise WaitFailedError(f"{description}: reached a failure state", last=last)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WaitTimeoutError(f"{description}: not reached within {timeout:.0f}s", last=last)
        logger.debug("waiting for %s", description)
        time.sleep(min(interval, remaining))


async def async_wait_until(
    fetch: Callable[[], Awaitable[T]],
    done: Callable[[T], bool],
    *,
    failed: Callable[[T], bool] | None = None,
    timeout: float = 300.0,
    interval: float = 5.0,
    description: str = "condition",
) -> T:
    """Async counterpart of :func:`wait_until`."""
    deadline = time.monotonic() + timeout
    while True:
        last = await fetch()
        if done(last):
            return last
        if failed is not None and failed(last):
            raise WaitFailedError(f"{description}: reached a failure state", last=last)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WaitTimeoutError(f"{description}: not reached within {timeout:.0f}s", last=last)
        logger.debug("waiting for %s", description)
        await asyncio.sleep(min(interval, remaining))


def state_in(attr: str, states: Collection[Any]) -> Callable[[Any], bool]:
    """Predicate: ``getattr(obj, attr)`` is one of ``states`` (enum or string values)."""
    wanted = {str(getattr(s, "value", s)) for s in states}

    def check(obj: Any) -> bool:
        value = getattr(obj, attr, None)
        return value is not None and str(getattr(value, "value", value)) in wanted

    return check
