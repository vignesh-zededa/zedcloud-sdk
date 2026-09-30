"""The pytest plugin skips cleanly without a tenant and guards writes."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]


def test_live_tests_skip_without_a_tenant(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("ZEDCLOUD_PROFILE", "ZEDCLOUD_BASE_URL", "ZEDCLOUD_TOKEN", "ZEDCLOUD_USERNAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ZEDCLOUD_CONFIG", str(pytester.path / "absent.toml"))
    pytester.makepyfile("def test_x(zedcloud_client):\n    raise AssertionError('ran')\n")
    pytester.runpytest().assert_outcomes(skipped=1)


def test_integration_tests_need_allow_writes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = pytester.path / "config.toml"
    cfg.write_text(
        '[profiles.ro]\nbase_url = "https://x"\ntoken = "t"\n'
        '[profiles.rw]\nbase_url = "https://x"\ntoken = "t"\nallow_writes = true\n'
    )
    cfg.chmod(0o600)
    monkeypatch.setenv("ZEDCLOUD_CONFIG", str(cfg))
    pytester.makepyfile("import pytest\n@pytest.mark.integration\ndef test_write():\n    pass\n")
    pytester.runpytest("--zedcloud-profile", "ro").assert_outcomes(skipped=1)
    pytester.runpytest("--zedcloud-profile", "rw").assert_outcomes(passed=1)
