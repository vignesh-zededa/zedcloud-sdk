"""Shared MCP tool descriptor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from zedcloud import ZedcloudClient

DumpFn = Callable[[Any], str]
ClientFactory = Callable[[], ZedcloudClient]
Handler = Callable[..., str]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    make_handler: Callable[[ClientFactory, DumpFn], Handler]

    def bind(self, get_client: ClientFactory, dump: DumpFn) -> Handler:
        return self.make_handler(get_client, dump)
