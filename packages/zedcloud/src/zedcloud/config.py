"""Connection settings and multi-tenant profiles.

A *profile* names one tenant connection: a controller URL plus credentials for
one user. Profiles live in a TOML file (``~/.config/zedcloud/config.toml``, or
``$ZEDCLOUD_CONFIG``)::

    default = "acme-prod"

    [profiles.acme-prod]
    base_url = "https://zedcontrol.zededa.net"
    token_env = "ACME_ZEDCLOUD_TOKEN"       # read the session/API token from an env var
    description = "Acme production (read-only)"

    [profiles.lab]
    base_url = "https://zedcontrol.zededa.net"
    username = "me@example.com"
    password_command = ["security", "find-generic-password", "-s", "zedcloud-lab", "-w"]
    enterprise = "lab-enterprise"            # enterprise to log into, if the user has several
    allow_writes = true                      # consulted by the MCP server, not the SDK

Each secret (``token``, ``password``, ``api_key``) can be given inline, via
``<name>_env`` (environment variable), ``<name>_command`` (a command whose
stdout is the secret — e.g. a password manager CLI), or ``<name>_keyring = true``
(OS keychain, service ``zedcloud``, entry ``<profile>:<name>``; needs the
``keyring`` extra). Secrets are resolved when a client is created, never at
import time.

Without a profile, configuration comes from ``ZEDCLOUD_*`` environment
variables: ``ZEDCLOUD_BASE_URL`` plus ``ZEDCLOUD_TOKEN`` or
``ZEDCLOUD_USERNAME``/``ZEDCLOUD_PASSWORD`` (optionally ``ZEDCLOUD_ENTERPRISE``).
``ZEDCLOUD_PROFILE`` selects a profile from the file instead.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
import warnings
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from zedcloud.errors import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_BASE_URL = "https://zedcontrol.zededa.net"
KEYRING_SERVICE = "zedcloud"
_SECRETS = ("token", "password", "api_key")


def default_config_path() -> Path:
    if env := os.environ.get("ZEDCLOUD_CONFIG"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "zedcloud" / "config.toml"


@dataclass(frozen=True)
class TokenCredentials:
    """An existing session or API token, sent as ``Authorization: Bearer``."""

    token: str

    def __repr__(self) -> str:
        return "TokenCredentials(token=***)"


@dataclass(frozen=True)
class PasswordCredentials:
    """Username/password; the SDK logs in and re-logs in when the session expires."""

    username: str
    password: str
    enterprise: str | None = None
    realm: str | None = None

    def __repr__(self) -> str:
        return (
            f"PasswordCredentials(username={self.username!r}, password=***, "
            f"enterprise={self.enterprise!r})"
        )


Credentials = TokenCredentials | PasswordCredentials


@dataclass(frozen=True)
class ZedcloudConfig:
    """Fully resolved settings for one client.

    Attributes:
        base_url: Controller origin, e.g. ``https://zedcontrol.zededa.net``.
        credentials: How to authenticate.
        api_key: ``X-API-KEY`` for the Kubernetes service; defaults to the session token.
        timeout: Per-request timeout in seconds.
        max_retries: Retries for transient failures (see ``zedcloud._transport``).
        retry_backoff: First retry delay in seconds; doubles per attempt.
        verify: TLS verification: ``True``, ``False``, or a CA bundle path.
        profile: Name of the profile this came from, if any.
        description: Free-form label for the tenant.
        allow_writes: Whether tools built on the SDK (the MCP server) may modify this tenant.
    """

    base_url: str
    credentials: Credentials
    api_key: str | None = None
    timeout: float = 30.0
    max_retries: int = 3
    retry_backoff: float = 0.5
    verify: bool | str = True
    profile: str | None = None
    description: str | None = None
    allow_writes: bool = False
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def api_root(self) -> str:
        """Origin plus the ``/api`` base path shared by every service."""
        base = self.base_url.rstrip("/")
        return base if base.endswith("/api") else f"{base}/api"

    @property
    def label(self) -> str:
        return self.profile or self.base_url

    def __repr__(self) -> str:
        return (
            f"ZedcloudConfig(base_url={self.base_url!r}, profile={self.profile!r}, "
            f"credentials={self.credentials!r})"
        )

    @classmethod
    def from_env(cls, **overrides: Any) -> ZedcloudConfig:
        """Build from ``ZEDCLOUD_*`` environment variables plus explicit overrides."""
        return resolve_config(**overrides)


@dataclass(frozen=True)
class Profile:
    """One entry of the profiles file, before secrets are resolved."""

    name: str
    base_url: str = DEFAULT_BASE_URL
    description: str | None = None
    username: str | None = None
    enterprise: str | None = None
    realm: str | None = None
    timeout: float | None = None
    max_retries: int | None = None
    verify: bool | str | None = None
    allow_writes: bool = False
    secrets: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def auth_kind(self) -> str:
        if any(k.startswith("token") for k in self.secrets):
            return "token"
        return "password" if self.username else "none"

    def resolve(self, **overrides: Any) -> ZedcloudConfig:
        """Resolve secrets and produce a :class:`ZedcloudConfig`."""
        return resolve_config(profile=self, **overrides)


def load_profiles(path: Path | str | None = None) -> tuple[dict[str, Profile], str | None]:
    """Read the profiles file. Returns ``(profiles, default_profile_name)``."""
    path = Path(path).expanduser() if path else default_config_path()
    if not path.exists():
        return {}, None
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    raw_profiles = data.get("profiles") or {}
    if not isinstance(raw_profiles, dict):
        raise ConfigError(f"{path}: [profiles] must be a table")
    known = {f.name for f in fields(Profile)} - {"name", "secrets"}
    secret_keys = {
        f"{s}{suffix}" for s in _SECRETS for suffix in ("", "_env", "_command", "_keyring")
    }
    profiles: dict[str, Profile] = {}
    has_inline_secret = False
    for name, raw in raw_profiles.items():
        if not isinstance(raw, dict):
            raise ConfigError(f"{path}: profile {name!r} must be a table")
        unknown = set(raw) - known - secret_keys
        if unknown:
            raise ConfigError(f"{path}: profile {name!r} has unknown keys: {sorted(unknown)}")
        secrets = {k: v for k, v in raw.items() if k in secret_keys}
        has_inline_secret |= any(k in _SECRETS for k in secrets)
        profiles[name] = Profile(
            name=name, secrets=secrets, **{k: v for k, v in raw.items() if k in known}
        )
    if has_inline_secret:
        _warn_if_world_readable(path)
    default = data.get("default")
    if default is not None and default not in profiles:
        raise ConfigError(f"{path}: default profile {default!r} is not defined")
    return profiles, default


def get_profile(name: str | None = None, path: Path | str | None = None) -> Profile:
    """Look up a profile by name, falling back to ``$ZEDCLOUD_PROFILE`` then the default."""
    profiles, default = load_profiles(path)
    wanted = name or os.environ.get("ZEDCLOUD_PROFILE") or default
    if not wanted:
        raise ConfigError(f"no profile given and no default set in {path or default_config_path()}")
    if wanted not in profiles:
        available = ", ".join(sorted(profiles)) or "none"
        raise ConfigError(f"unknown profile {wanted!r} (available: {available})")
    return profiles[wanted]


def resolve_config(
    *,
    profile: Profile | str | None = None,
    base_url: str | None = None,
    token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    enterprise: str | None = None,
    realm: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
    verify: bool | str | None = None,
    config_path: Path | str | None = None,
) -> ZedcloudConfig:
    """Merge explicit arguments > profile (or environment) into a config.

    A profile is used when ``profile`` is given or ``ZEDCLOUD_PROFILE`` is set;
    otherwise ``ZEDCLOUD_*`` environment variables are the fallback source.
    """
    env = os.environ
    if isinstance(profile, str) or (profile is None and env.get("ZEDCLOUD_PROFILE")):
        profile = get_profile(profile if isinstance(profile, str) else None, config_path)

    if isinstance(profile, Profile):
        src_base = profile.base_url
        src_token = _resolve_secret(profile, "token")
        src_user = profile.username
        src_password = _resolve_secret(profile, "password") if src_user and not src_token else None
        src_api_key = _resolve_secret(profile, "api_key")
        src_enterprise, src_realm = profile.enterprise, profile.realm
        src_timeout, src_retries, src_verify = profile.timeout, profile.max_retries, profile.verify
    else:
        src_base = env.get("ZEDCLOUD_BASE_URL")
        src_token = env.get("ZEDCLOUD_TOKEN")
        src_user = env.get("ZEDCLOUD_USERNAME")
        src_password = env.get("ZEDCLOUD_PASSWORD")
        src_api_key = env.get("ZEDCLOUD_API_KEY")
        src_enterprise = env.get("ZEDCLOUD_ENTERPRISE")
        src_realm = env.get("ZEDCLOUD_REALM")
        src_timeout = _env_float("ZEDCLOUD_TIMEOUT")
        src_retries = _env_int("ZEDCLOUD_MAX_RETRIES")
        src_verify = _env_verify("ZEDCLOUD_VERIFY")

    resolved_base = base_url or src_base
    if not resolved_base:
        raise ConfigError(
            "base URL is required: pass base_url=, set ZEDCLOUD_BASE_URL, or use a profile"
        )

    credentials: Credentials
    explicit_password = username is not None or password is not None
    if token:
        credentials = TokenCredentials(token)
    elif explicit_password or (not src_token and src_user):
        user = username or src_user
        secret = password if password is not None else src_password
        if not user or not secret:
            raise ConfigError("username and password must both be provided")
        credentials = PasswordCredentials(
            user, secret, enterprise or src_enterprise, realm or src_realm
        )
    elif src_token:
        credentials = TokenCredentials(src_token)
    else:
        raise ConfigError(
            "no credentials: pass token= or username=/password=, set ZEDCLOUD_TOKEN "
            "(or ZEDCLOUD_USERNAME/ZEDCLOUD_PASSWORD), or configure a profile"
        )

    prof = profile if isinstance(profile, Profile) else None
    return ZedcloudConfig(
        base_url=resolved_base.rstrip("/"),
        credentials=credentials,
        api_key=api_key or src_api_key,
        timeout=timeout if timeout is not None else (src_timeout or 30.0),
        max_retries=max_retries
        if max_retries is not None
        else (src_retries if src_retries is not None else 3),
        verify=verify if verify is not None else (src_verify if src_verify is not None else True),
        profile=prof.name if prof else None,
        description=prof.description if prof else None,
        allow_writes=prof.allow_writes if prof else False,
    )


def with_overrides(config: ZedcloudConfig, **changes: Any) -> ZedcloudConfig:
    """Return a copy of ``config`` with fields replaced."""
    return replace(config, **changes)


def _resolve_secret(profile: Profile, name: str) -> str | None:
    s = profile.secrets
    if s.get(name):
        return str(s[name])
    if env_name := s.get(f"{name}_env"):
        value = os.environ.get(env_name)
        if not value:
            raise ConfigError(f"profile {profile.name!r}: environment variable {env_name} is empty")
        return value
    if command := s.get(f"{name}_command"):
        argv = shlex.split(command) if isinstance(command, str) else [str(c) for c in command]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConfigError(f"profile {profile.name!r}: {name}_command failed: {exc}") from exc
        value = result.stdout.strip()
        if not value:
            raise ConfigError(f"profile {profile.name!r}: {name}_command printed nothing")
        return value
    if s.get(f"{name}_keyring"):
        try:
            import keyring
        except ImportError as exc:
            raise ConfigError(
                f"profile {profile.name!r} uses {name}_keyring; install zedcloud[keyring]"
            ) from exc
        value = keyring.get_password(KEYRING_SERVICE, f"{profile.name}:{name}")
        if not value:
            raise ConfigError(
                f"profile {profile.name!r}: no keyring entry "
                f"{KEYRING_SERVICE}/{profile.name}:{name}"
            )
        return value
    return None


def _warn_if_world_readable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if os.name == "posix" and mode & (stat.S_IRGRP | stat.S_IROTH):
        warnings.warn(
            f"{path} contains inline secrets but is readable by other users; run: chmod 600 {path}",
            stacklevel=3,
        )


def _env_float(name: str) -> float | None:
    value = os.environ.get(name)
    return float(value) if value else None


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value else None


def _env_verify(name: str) -> bool | str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    if value.lower() in {"0", "false", "no"}:
        return False
    if value.lower() in {"1", "true", "yes"}:
        return True
    return value
