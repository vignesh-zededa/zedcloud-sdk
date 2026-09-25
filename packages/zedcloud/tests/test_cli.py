"""``zedcloud`` CLI."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from zedcloud.cli import main

from .conftest import API


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        'default = "prod"\n'
        '[profiles.prod]\nbase_url = "https://zc.example"\ntoken_env = "T"\ndescription = "Prod"\n'
        '[profiles.lab]\nbase_url = "https://zc.example"\ntoken_env = "T"\nallow_writes = true\n'
    )
    monkeypatch.setenv("ZEDCLOUD_CONFIG", str(path))
    monkeypatch.setenv("T", "tok")
    monkeypatch.delenv("ZEDCLOUD_PROFILE", raising=False)
    return path


def test_profiles(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profiles"]) == 0
    out = capsys.readouterr().out
    assert "* prod" in out and "read-only" in out and "Prod" in out
    assert "  lab" in out and "writes" in out


def test_ops_search_and_show(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ops", "search", "reboot edge node", "--limit", "1"]) == 0
    assert "nodes.reboot" in capsys.readouterr().out
    assert main(["ops", "show", "nodes.reboot"]) == 0
    assert "[destructive]" in capsys.readouterr().out


def test_call_read(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with respx.mock(base_url=API) as api:
        route = api.get("/v1/devices").mock(
            return_value=httpx.Response(200, json={"list": [{"name": "gw"}]})
        )
        assert main(["-p", "prod", "call", "nodes.query_edge_nodes", "-q", "page_size=1"]) == 0
    assert route.calls.last.request.url.params["next.pageSize"] == "1"
    assert json.loads(capsys.readouterr().out)["list"][0]["name"] == "gw"


def test_call_write_requires_yes(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["call", "nodes.reboot", "--path", "id=x"]) == 2
    assert "--yes" in capsys.readouterr().err
    with respx.mock(base_url=API) as api:
        route = api.put("/v1/devices/id/x/reboot").mock(return_value=httpx.Response(200, json={}))
        assert main(["call", "nodes.reboot", "--path", "id=x", "--yes"]) == 0
    assert route.called


def test_api_errors_exit_nonzero(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with respx.mock(base_url=API) as api:
        api.get("/v1/devices/id/x").mock(return_value=httpx.Response(404, json={"message": "gone"}))
        assert main(["call", "nodes.get_edge_node", "--path", "id=x"]) == 1
    assert "gone" in capsys.readouterr().err
