"""lookup_* resolution, waiters, and job helpers."""

from __future__ import annotations

import httpx
import pytest
import respx

from zedcloud import AsyncZedcloudClient, WaitFailedError, WaitTimeoutError, ZedcloudClient
from zedcloud.models import RunState, ZsrvResponse

UUID = "0b1b3c7e-9d52-4d0f-8a4b-1f2e3d4c5b6a"


def test_lookup_by_name(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices/name/gw-7").mock(
        return_value=httpx.Response(200, json={"id": UUID})
    )
    assert client.nodes.lookup_edge_node("gw-7").id == UUID
    assert route.called


def test_lookup_by_id(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get(f"/v1/devices/id/{UUID}").mock(
        return_value=httpx.Response(200, json={"id": UUID})
    )
    client.nodes.lookup_edge_node(UUID)
    assert route.called


def test_uuid_shaped_name_falls_back_to_name(client: ZedcloudClient, api: respx.MockRouter) -> None:
    api.get(f"/v1/devices/id/{UUID}").mock(return_value=httpx.Response(404))
    by_name = api.get(f"/v1/devices/name/{UUID}").mock(return_value=httpx.Response(200, json={}))
    client.nodes.lookup_edge_node(UUID)
    assert by_name.called


def test_lookup_project_alias(client: ZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/projects/name/plant-7").mock(
        return_value=httpx.Response(200, json={"name": "plant-7"})
    )
    assert client.nodes.lookup_project("plant-7").name == "plant-7"


async def test_async_lookup(aclient: AsyncZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/apps/instances/name/web").mock(
        return_value=httpx.Response(200, json={"name": "web"})
    )
    assert (await aclient.apps.lookup_edge_application_instance("web")).name == "web"


def status(state: str) -> httpx.Response:
    return httpx.Response(200, json={"runState": state})


def test_wait_for_edge_node(client: ZedcloudClient, api: respx.MockRouter) -> None:
    route = api.get("/v1/devices/name/gw/status").mock(
        side_effect=[
            status("RUN_STATE_REBOOTING"),
            status("RUN_STATE_BOOTING"),
            status("RUN_STATE_ONLINE"),
        ]
    )
    result = client.nodes.wait_for_edge_node("gw", interval=0)
    assert result.run_state is RunState.RUN_STATE_ONLINE
    assert route.call_count == 3


def test_wait_times_out_with_last_value(client: ZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/devices/name/gw/status").mock(return_value=status("RUN_STATE_OFFLINE"))
    with pytest.raises(WaitTimeoutError) as info:
        client.nodes.wait_for_edge_node("gw", timeout=0, interval=0)
    assert info.value.last.run_state == "RUN_STATE_OFFLINE"


def test_app_instance_error_state_fails_fast(client: ZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/apps/instances/name/web/status").mock(
        side_effect=[status("RUN_STATE_DOWNLOADING"), status("RUN_STATE_ERROR")]
    )
    with pytest.raises(WaitFailedError):
        client.apps.wait_for_app_instance("web", interval=0)


def job(status_value: str) -> httpx.Response:
    return httpx.Response(200, json={"id": "j1", "status": status_value})


def test_wait_for_job_from_response(client: ZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/jobs/id/j1").mock(
        side_effect=[job("JOB_STATUS_INPROGRESS"), job("JOB_STATUS_COMPLETED")]
    )
    done = client.jobs.wait_for_job(ZsrvResponse(job_id="j1"), interval=0)
    assert done.status == "JOB_STATUS_COMPLETED"


def test_failed_job_raises(client: ZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/jobs/id/j1").mock(return_value=job("JOB_STATUS_FAILED"))
    with pytest.raises(WaitFailedError):
        client.jobs.wait_for_job("j1", interval=0)


def test_wait_for_job_needs_a_job_id(client: ZedcloudClient) -> None:
    with pytest.raises(ValueError, match="did not start a job"):
        client.jobs.wait_for_job(ZsrvResponse())


async def test_async_wait_for_job(aclient: AsyncZedcloudClient, api: respx.MockRouter) -> None:
    api.get("/v1/jobs/id/j1").mock(
        side_effect=[job("JOB_STATUS_READY"), job("JOB_STATUS_COMPLETED")]
    )
    assert (await aclient.jobs.wait_for_job("j1", interval=0)).id == "j1"
