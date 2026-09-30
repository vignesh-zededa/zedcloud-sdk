"""Tenant selection for the MCP server.

Each tenant is a profile from the zedcloud profiles file. One tenant is
*active* per server process; every tool also accepts an explicit ``tenant``.
Clients are created lazily (secrets are resolved on first use) and cached.
Without a profiles file, ``ZEDCLOUD_*`` environment variables define a single
tenant named ``env``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zedcloud import AsyncZedcloudClient, ConfigError
from zedcloud.config import Profile, ZedcloudConfig, load_profiles, resolve_config

ENV_TENANT = "env"


@dataclass
class Tenant:
    name: str
    base_url: str
    description: str | None
    auth: str
    allow_writes: bool
    profile: Profile | None = None
    config: ZedcloudConfig | None = None


class TenantError(Exception):
    """A tenant is unknown, not selected, or cannot be connected."""


class TenantManager:
    def __init__(self, config_path: Path | str | None = None, *, read_only: bool = False) -> None:
        self.read_only = read_only
        self._clients: dict[str, AsyncZedcloudClient] = {}
        profiles, default = load_profiles(config_path)
        self.tenants: dict[str, Tenant] = {
            name: Tenant(
                name=name,
                base_url=p.base_url,
                description=p.description,
                auth=p.auth_kind,
                allow_writes=p.allow_writes,
                profile=p,
            )
            for name, p in profiles.items()
        }
        if not self.tenants and os.environ.get("ZEDCLOUD_BASE_URL"):
            try:
                config = resolve_config()
            except ConfigError:
                config = None
            if config is not None:
                self.tenants[ENV_TENANT] = Tenant(
                    name=ENV_TENANT,
                    base_url=config.base_url,
                    description="from ZEDCLOUD_* environment variables",
                    auth=type(config.credentials).__name__.replace("Credentials", "").lower(),
                    allow_writes=os.environ.get("ZEDCLOUD_MCP_ALLOW_WRITES", "").lower()
                    in {"1", "true", "yes"},
                    config=config,
                )
        env_default = os.environ.get("ZEDCLOUD_PROFILE")
        if env_default in self.tenants:
            self.active: str | None = env_default
        elif default:
            self.active = default
        elif len(self.tenants) == 1:
            self.active = next(iter(self.tenants))
        else:
            self.active = None

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "tenant": t.name,
                "base_url": t.base_url,
                "description": t.description,
                "auth": t.auth,
                "writes_allowed": self.writes_allowed(t.name),
                "active": t.name == self.active,
            }
            for t in self.tenants.values()
        ]

    def resolve(self, tenant: str | None) -> str:
        name = tenant or self.active
        if not name:
            available = ", ".join(self.tenants) or "none configured"
            raise TenantError(f"no tenant selected. Call use_tenant with one of: {available}")
        if name not in self.tenants:
            available = ", ".join(self.tenants) or "none configured"
            raise TenantError(f"unknown tenant {name!r}. Available: {available}")
        return name

    def select(self, tenant: str) -> str:
        self.active = self.resolve(tenant)
        return self.active

    def writes_allowed(self, tenant: str) -> bool:
        return not self.read_only and self.tenants[tenant].allow_writes

    def client(self, tenant: str) -> AsyncZedcloudClient:
        name = self.resolve(tenant)
        if name not in self._clients:
            t = self.tenants[name]
            try:
                config = t.config or (t.profile.resolve() if t.profile else None)
            except ConfigError as exc:
                raise TenantError(f"tenant {name!r}: {exc}") from exc
            if config is None:
                raise TenantError(f"tenant {name!r} has no configuration")
            self._clients[name] = AsyncZedcloudClient(config=config)
        return self._clients[name]

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
