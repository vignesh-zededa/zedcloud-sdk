"""Models must tolerate API responses the spec does not describe."""

from __future__ import annotations

from datetime import datetime

from zedcloud.models import AdminState, DeviceConfig, DeviceConfigList, UpdateEdgeNodeBody

DEVICE = {"id": "1", "name": "d", "adminState": "ADMIN_STATE_ACTIVE"}


def test_unknown_enum_values_are_accepted() -> None:
    dev = DeviceConfig.model_validate({**DEVICE, "adminState": "ADMIN_STATE_FROM_THE_FUTURE"})
    assert isinstance(dev.admin_state, AdminState)
    assert dev.admin_state == "ADMIN_STATE_FROM_THE_FUTURE"
    assert not dev.admin_state.is_known
    assert DeviceConfig.model_validate(DEVICE).admin_state is AdminState.ADMIN_STATE_ACTIVE
    assert AdminState.ADMIN_STATE_ACTIVE.is_known


def test_unknown_fields_round_trip() -> None:
    dev = DeviceConfig.model_validate({**DEVICE, "brandNewField": {"k": 1}})
    assert dev.to_api()["brandNewField"] == {"k": 1}


def test_spec_required_fields_may_be_missing_in_responses() -> None:
    page = DeviceConfigList.model_validate({"list": [{"id": "1"}], "next": {}})
    assert page.summary_by_state is None
    assert page.list[0].id == "1"


def test_int64_strings_are_coerced() -> None:
    page = DeviceConfigList.model_validate({"next": {"pageNum": "3", "totalPages": 7.0}})
    assert page.next.page_num == 3 and page.next.total_pages == 7


def test_unparseable_timestamps_keep_the_raw_value() -> None:
    from zedcloud.models import AAAFrontendGenerateTokenResponse as Token

    good = Token.model_validate({"expiresAt": "2026-01-02T03:04:05Z"})
    assert isinstance(good.expires_at, datetime)
    odd = Token.model_validate({"expiresAt": "yesterday-ish"})
    assert odd.expires_at == "yesterday-ish"


def test_snake_and_camel_case_construction() -> None:
    body = UpdateEdgeNodeBody(name="d", project_id="p", modelId="m")
    assert body.to_api() == {"name": "d", "projectId": "p", "modelId": "m"}


def test_dump_emits_no_serializer_warnings(recwarn) -> None:
    DeviceConfig.model_validate({**DEVICE, "utype": "SOMETHING_NEW"}).to_api()
    assert not [w for w in recwarn if "serializ" in str(w.message).lower()]


def test_update_bodies_are_typed() -> None:
    import inspect

    from zedcloud import ZedcloudClient

    sig = inspect.signature(ZedcloudClient.__init__)  # noqa: F841 — import check
    from zedcloud._generated.services.nodes import NodesService

    ann = inspect.signature(NodesService.update_edge_node).parameters["body"].annotation
    assert "UpdateEdgeNodeBody" in str(ann)
