"""Profiles file and environment configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from zedcloud import ConfigError, PasswordCredentials, TokenCredentials, ZedcloudClient
from zedcloud.config import load_profiles, resolve_config

PROFILES = """
default = "prod"

[profiles.prod]
base_url = "https://prod.example"
token_env = "PROD_TOKEN"
description = "Production"

[profiles.lab]
base_url = "https://lab.example"
username = "me@example.com"
password_command = ["{python}", "-c", "print('s3cret')"]
enterprise = "lab-ent"
allow_writes = true
timeout = 5
"""


@pytest.fixture
def profiles_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(PROFILES.replace("{python}", sys.executable.replace("\\", "\\\\")))
    path.chmod(0o600)
    for var in ("ZEDCLOUD_PROFILE", "ZEDCLOUD_BASE_URL", "ZEDCLOUD_TOKEN", "ZEDCLOUD_USERNAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ZEDCLOUD_CONFIG", str(path))
    monkeypatch.setenv("PROD_TOKEN", "prod-tok")
    return path


def test_load_profiles(profiles_file: Path) -> None:
    profiles, default = load_profiles()
    assert default == "prod"
    assert set(profiles) == {"prod", "lab"}
    assert profiles["prod"].auth_kind == "token"
    assert profiles["lab"].auth_kind == "password"
    assert "s3cret" not in repr(profiles["lab"])


def test_default_profile_with_env_token(profiles_file: Path) -> None:
    config = resolve_config(profile="prod")
    assert config.credentials == TokenCredentials("prod-tok")
    assert config.base_url == "https://prod.example" and config.profile == "prod"
    assert config.allow_writes is False


def test_password_command_profile(profiles_file: Path) -> None:
    config = ZedcloudClient.from_profile("lab").config
    assert config.credentials == PasswordCredentials("me@example.com", "s3cret", "lab-ent")
    assert config.timeout == 5 and config.allow_writes is True


def test_zedcloud_profile_env_var(profiles_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZEDCLOUD_PROFILE", "lab")
    assert ZedcloudClient().config.profile == "lab"


def test_explicit_args_override_profile(profiles_file: Path) -> None:
    config = resolve_config(profile="prod", base_url="https://other.example", token="t2")
    assert config.base_url == "https://other.example"
    assert config.credentials == TokenCredentials("t2")


def test_unknown_profile(profiles_file: Path) -> None:
    with pytest.raises(ConfigError, match="unknown profile 'nope'.*lab, prod"):
        resolve_config(profile="nope")


def test_typos_in_profiles_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[profiles.x]\nbase_url = "https://x"\ntokn = "oops"\n')
    with pytest.raises(ConfigError, match="unknown keys.*tokn"):
        load_profiles(path)


def test_missing_env_secret_is_reported(
    profiles_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PROD_TOKEN")
    with pytest.raises(ConfigError, match="PROD_TOKEN is empty"):
        resolve_config(profile="prod")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_world_readable_inline_secrets_warn(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[profiles.x]\nbase_url = "https://x"\ntoken = "inline"\n')
    path.chmod(0o644)
    with pytest.warns(UserWarning, match="chmod 600"):
        load_profiles(path)


def test_environment_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEDCLOUD_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.delenv("ZEDCLOUD_PROFILE", raising=False)
    monkeypatch.delenv("ZEDCLOUD_TOKEN", raising=False)
    monkeypatch.setenv("ZEDCLOUD_BASE_URL", "https://env.example/")
    monkeypatch.setenv("ZEDCLOUD_USERNAME", "u")
    monkeypatch.setenv("ZEDCLOUD_PASSWORD", "p")
    config = resolve_config()
    assert config.base_url == "https://env.example"
    assert config.api_root == "https://env.example/api"
    assert isinstance(config.credentials, PasswordCredentials)


def test_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ZEDCLOUD_PROFILE", "ZEDCLOUD_TOKEN", "ZEDCLOUD_USERNAME", "ZEDCLOUD_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ConfigError, match="no credentials"):
        resolve_config(base_url="https://x")
