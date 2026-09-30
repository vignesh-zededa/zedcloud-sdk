"""End-to-end tests of the MCP tools against a mocked Zedcloud controller."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from zedcloud_mcp.guard import WriteGuard
from zedcloud_mcp.server import create_server
from zedcloud_mcp.tenants import TenantManager

API = "https://zc.example/api"
UUID = "0b1b3c7e-9d52-4d0f-8a4b-1f2e3d4c5b6a"
PROFILES = """
default = "prod"
[profiles.prod]
base_url = "https://zc.example"
token = "prod-token"
description = "Production"
[profiles.lab]
base_url = "https://zc.example"
token = "lab-token"
allow_writes = true
"""


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("ZEDCLOUD_PROFILE", raising=False)
    path = tmp_path / "config.toml"
    path.write_text(PROFILES)
    path.chmod(0o600)
    return path


@pytest.fixture
def audit(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        yield router


def make(config_file: Path, audit: Path, **kwargs: Any):
    read_only = kwargs.pop("read_only", False)
    return create_server(
        TenantManager(config_file, read_only=read_only), WriteGuard(audit_path=audit), **kwargs
    )


@pytest.fixture
def server(config_file: Path, audit: Path):
    return make(config_file, audit)


async def call(server, tool: str, **args: Any) -> dict[str, Any]:
    result = await server.call_tool(tool, args)
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


# ----------------------------------------------------------------- tenants


async def test_list_and_switch_tenants(server, api: respx.MockRouter) -> None:
    listed = await call(server, "list_tenants")
    assert listed["active"] == "prod"
    by_name = {t["tenant"]: t for t in listed["tenants"]}
    assert by_name["prod"]["writes_allowed"] is False and by_name["lab"]["writes_allowed"] is True

    session = api.get("/v1/sessions/self").mock(
        return_value=httpx.Response(200, json={"userId": "u"})
    )
    switched = await call(server, "use_tenant", tenant="lab")
    assert switched["active"] == "lab"
    assert session.calls.last.request.headers["Authorization"] == "Bearer lab-token"
    assert (await call(server, "list_tenants"))["active"] == "lab"


async def test_per_call_tenant_override(server, api: respx.MockRouter) -> None:
    route = api.get("/v1/sessions/self").mock(return_value=httpx.Response(200, json={}))
    assert (await call(server, "whoami", tenant="lab"))["tenant"] == "lab"
    assert route.calls.last.request.headers["Authorization"] == "Bearer lab-token"
    assert (await call(server, "whoami"))["tenant"] == "prod"


async def test_unknown_tenant(server) -> None:
    with pytest.raises(ToolError, match="unknown tenant 'nope'.*prod"):
        await server.call_tool("whoami", {"tenant": "nope"})


# ----------------------------------------------------------------- task tools


def nodes_page() -> httpx.Response:
    items = [
        {"name": "gw-1", "id": "1", "runState": "RUN_STATE_ONLINE", "projectName": "p"},
        {"name": "gw-2", "id": "2", "runState": "RUN_STATE_OFFLINE", "projectName": "p"},
        {"name": "gw-3", "id": "3", "runState": "RUN_STATE_ONLINE", "projectName": "p"},
    ]
    return httpx.Response(200, json={"list": items, "next": {"totalPages": 1}})


async def test_fleet_health(server, api: respx.MockRouter) -> None:
    api.get("/v1/devices/status").mock(return_value=nodes_page())
    api.get("/v1/apps/instances/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "list": [{"name": "web", "runState": "RUN_STATE_ERROR", "deviceName": "gw-2"}],
                "next": {"totalPages": 1},
            },
        )
    )
    health = await call(server, "fleet_health", project="p")
    nodes = health["edge_nodes"]
    assert nodes["by_run_state"] == {"RUN_STATE_ONLINE": 2, "RUN_STATE_OFFLINE": 1}
    assert nodes["not_online"] == [
        {"name": "gw-2", "id": "2", "project": "p", "run_state": "RUN_STATE_OFFLINE"}
    ]
    assert health["app_instances"]["not_online"][0]["edge_node"] == "gw-2"
    assert health["tenant"] == "prod"


async def test_list_edge_nodes_normalises_state_filter(server, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices/status").mock(return_value=nodes_page())
    result = await call(server, "list_edge_nodes", run_state="RUN_STATE_OFFLINE", max_items=2)
    assert route.calls.last.request.url.params["runState"] == "OFFLINE"
    assert result["count"] == 2 and result["more_available"] is True


async def test_get_edge_node_by_name_with_status(server, api: respx.MockRouter) -> None:
    api.get("/v1/devices/name/gw-1").mock(
        return_value=httpx.Response(200, json={"id": UUID, "name": "gw-1"})
    )
    api.get(f"/v1/devices/id/{UUID}/status").mock(
        return_value=httpx.Response(200, json={"runState": "RUN_STATE_ONLINE"})
    )
    result = await call(server, "get_edge_node", name_or_id="gw-1")
    assert result["config"]["name"] == "gw-1" and result["status"]["runState"] == "RUN_STATE_ONLINE"


async def test_recent_events(server, api: respx.MockRouter) -> None:
    api.get("/v1/devices/name/gw-1/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "list": [{"severity": "SEVERITY_ERROR", "description": "disk full"}],
                "next": {"totalPages": 1},
            },
        )
    )
    result = await call(server, "recent_events", resource_type="edge_node", name="gw-1")
    assert result["events"] == [{"severity": "SEVERITY_ERROR", "description": "disk full"}]


async def test_api_errors_become_tool_errors(server, api: respx.MockRouter) -> None:
    api.get("/v1/devices/name/ghost").mock(
        return_value=httpx.Response(
            404, json={"error": [{"ec": "zMsgErrorNotFound", "details": "no such device"}]}
        )
    )
    with pytest.raises(ToolError, match=r"404 \(zMsgErrorNotFound\): no such device.*request_id="):
        await server.call_tool("get_edge_node", {"name_or_id": "ghost"})


# ----------------------------------------------------------------- full API


async def test_search_and_describe(server) -> None:
    found = await call(server, "search_operations", query="reboot edge node", limit=3)
    assert found["operations"][0]["operation_id"] == "EdgeNodeConfiguration_Reboot"
    assert found["operations"][0]["risk"] == "destructive"
    described = await call(server, "describe_operation", operation_id="nodes.update_edge_node")
    assert described["use_tool"] == "plan_write_operation"
    assert "projectId" in described["body"]["fields"]


async def test_call_read_operation(server, api: respx.MockRouter) -> None:
    api.get("/v1/datastores/id/d1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "d1",
                "name": "ds",
                "dsType": "DATASTORE_TYPE_S3",
                "secret": {"apiPasswd": "hunter2"},
            },
        )
    )
    result = await call(
        server, "call_read_operation", operation_id="storage.get_datastore", path={"id": "d1"}
    )
    assert "hunter2" not in json.dumps(result)
    trimmed = await call(
        server,
        "call_read_operation",
        operation_id="storage.get_datastore",
        path={"id": "d1"},
        fields=["name"],
    )
    assert trimmed["result"] == {"name": "ds"}


async def test_call_read_operation_refuses_writes(server) -> None:
    with pytest.raises(ToolError, match="use plan_write_operation"):
        await server.call_tool(
            "call_read_operation", {"operation_id": "nodes.reboot", "path": {"id": "1"}}
        )


# ----------------------------------------------------------------- writes


async def test_writes_refused_on_read_only_profile(server) -> None:
    with pytest.raises(ToolError, match="does not set allow_writes"):
        await server.call_tool(
            "plan_write_operation", {"operation_id": "nodes.reboot", "path": {"id": "1"}}
        )


async def test_read_only_flag_overrides_profiles(config_file: Path, audit: Path) -> None:
    server = make(config_file, audit, read_only=True)
    with pytest.raises(ToolError, match="--read-only"):
        await server.call_tool(
            "plan_write_operation",
            {"operation_id": "nodes.reboot", "path": {"id": "1"}, "tenant": "lab"},
        )


async def test_update_merges_previews_and_executes_exactly_the_plan(
    server, api: respx.MockRouter, audit: Path
) -> None:
    current = {
        "id": UUID,
        "name": "gw-1",
        "title": "Old",
        "projectId": "p",
        "modelId": "m",
        "tags": {"a": "b"},
    }
    api.get(f"/v1/devices/id/{UUID}").mock(return_value=httpx.Response(200, json=current))
    put = api.put(f"/v1/devices/id/{UUID}").mock(
        return_value=httpx.Response(
            200, json={"objectId": UUID, "operationStatus": "OPS_STATUS_COMPLETE"}
        )
    )
    plan = await call(
        server,
        "plan_write_operation",
        operation_id="nodes.update_edge_node",
        path={"id": UUID},
        body={"title": "New"},
        tenant="lab",
    )
    assert plan["tenant"] == "lab" and plan["risk"] == "write"
    assert plan["target"] == {"name": "gw-1", "id": UUID, "title": "Old"}
    assert plan["changes"] == [{"field": "title", "before": "Old", "after": "New"}]
    assert not put.called  # planning never writes

    done = await call(
        server, "execute_write_operation", confirmation_token=plan["confirmation_token"]
    )
    assert done["status"] == "done"
    sent = json.loads(put.calls.last.request.content)
    assert sent == {**current, "title": "New"}  # untouched fields preserved
    assert put.calls.last.request.headers["Authorization"] == "Bearer lab-token"

    with pytest.raises(ToolError, match="already used"):
        await server.call_tool(
            "execute_write_operation", {"confirmation_token": plan["confirmation_token"]}
        )

    events = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [e["event"] for e in events] == ["planned", "executed"]
    assert events[1]["tenant"] == "lab" and events[1]["request"] == f"PUT /v1/devices/id/{UUID}"


async def test_unmerged_update_warns_about_cleared_fields(server, api: respx.MockRouter) -> None:
    api.get(f"/v1/devices/id/{UUID}").mock(
        return_value=httpx.Response(200, json={"id": UUID, "name": "gw", "title": "T"})
    )
    plan = await call(
        server,
        "plan_write_operation",
        operation_id="nodes.update_edge_node",
        path={"id": UUID},
        body={"title": "T2"},
        merge_with_current=False,
        tenant="lab",
    )
    assert any("may be cleared" in w and "name" in w for w in plan["warnings"])


async def test_destructive_action_preview(server, api: respx.MockRouter) -> None:
    api.get(f"/v1/devices/id/{UUID}").mock(
        return_value=httpx.Response(200, json={"id": UUID, "name": "gw-1"})
    )
    reboot = api.put(f"/v1/devices/id/{UUID}/reboot").mock(
        return_value=httpx.Response(200, json={})
    )
    plan = await call(
        server, "plan_write_operation", operation_id="nodes.reboot", path={"id": UUID}, tenant="lab"
    )
    assert plan["warnings"][0].startswith("DESTRUCTIVE")
    assert plan["target"]["name"] == "gw-1"
    assert plan["request"] == f"PUT /api/v1/devices/id/{UUID}/reboot"
    await call(server, "execute_write_operation", confirmation_token=plan["confirmation_token"])
    assert reboot.call_count == 1


async def test_plan_rejects_missing_target(server, api: respx.MockRouter) -> None:
    api.get(f"/v1/devices/id/{UUID}").mock(
        return_value=httpx.Response(404, json={"message": "gone"})
    )
    with pytest.raises(ToolError, match="target not found"):
        await server.call_tool(
            "plan_write_operation",
            {"operation_id": "nodes.reboot", "path": {"id": UUID}, "tenant": "lab"},
        )


async def test_failed_execution_is_audited(server, api: respx.MockRouter, audit: Path) -> None:
    api.post("/v1/projects").mock(
        return_value=httpx.Response(
            409, json={"error": [{"ec": "zMsgErrorAlreadyExists", "details": "exists"}]}
        )
    )
    plan = await call(
        server,
        "plan_write_operation",
        operation_id="nodes.create_resource_group",
        body={"name": "p", "title": "P", "type": "TAG_TYPE_PROJECT"},
        tenant="lab",
    )
    with pytest.raises(ToolError, match="409"):
        await server.call_tool(
            "execute_write_operation", {"confirmation_token": plan["confirmation_token"]}
        )
    assert json.loads(audit.read_text().splitlines()[-1])["event"] == "failed"


async def test_audit_log_redacts_secrets(server, api: respx.MockRouter, audit: Path) -> None:
    api.post("/v1/datastores").mock(return_value=httpx.Response(200, json={}))
    await call(
        server,
        "plan_write_operation",
        operation_id="storage.create_datastore",
        body={"name": "ds", "secret": {"apiPasswd": "hunter2"}},
        tenant="lab",
    )
    assert "hunter2" not in audit.read_text()


async def test_human_approval_required_without_elicitation(
    config_file: Path, audit: Path, api: respx.MockRouter
) -> None:
    server = make(config_file, audit, require_human_approval=True)
    api.get(f"/v1/devices/id/{UUID}").mock(return_value=httpx.Response(200, json={"id": UUID}))
    reboot = api.put(f"/v1/devices/id/{UUID}/reboot")
    plan = await call(
        server, "plan_write_operation", operation_id="nodes.reboot", path={"id": UUID}, tenant="lab"
    )
    with pytest.raises(ToolError, match="elicitation"):
        await server.call_tool(
            "execute_write_operation", {"confirmation_token": plan["confirmation_token"]}
        )
    assert not reboot.called


async def test_tool_annotations(server) -> None:
    tools = {t.name: t for t in await server.list_tools()}
    assert tools["execute_write_operation"].annotations.destructive_hint is True
    for name in (
        "fleet_health",
        "list_edge_nodes",
        "call_read_operation",
        "plan_write_operation",
        "search_operations",
    ):
        assert tools[name].annotations.read_only_hint is True, name
