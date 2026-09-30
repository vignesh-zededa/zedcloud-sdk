"""Shared fixtures: clients pointed at a mocked controller."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import respx

from zedcloud import AsyncZedcloudClient, TokenCredentials, ZedcloudClient, ZedcloudConfig

BASE = "https://zc.example"
API = f"{BASE}/api"


def make_config(**overrides: object) -> ZedcloudConfig:
    settings: dict[str, object] = {
        "base_url": BASE,
        "credentials": TokenCredentials("tok"),
        "max_retries": 2,
        "retry_backoff": 0.0,
    }
    settings.update(overrides)
    return ZedcloudConfig(**settings)  # type: ignore[arg-type]


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        yield router


@pytest.fixture
def client(api: respx.MockRouter) -> Iterator[ZedcloudClient]:
    with ZedcloudClient(config=make_config()) as c:
        yield c


@pytest.fixture
async def aclient(api: respx.MockRouter) -> AsyncIterator[AsyncZedcloudClient]:
    async with AsyncZedcloudClient(config=make_config()) as c:
        yield c
