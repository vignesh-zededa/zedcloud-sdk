"""Token and username/password authentication."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zedcloud import AuthenticationError, PasswordCredentials, TokenCredentials, ZedcloudClient

from .conftest import make_config


def login_ok(token: str) -> httpx.Response:
    return httpx.Response(200, json={"cause": "OK", "userId": "u1", "token": {"base64": token}})


def password_client(**creds: str) -> ZedcloudClient:
    creds = {"username": "me@example.com", "password": "pw", **creds}
    return ZedcloudClient(config=make_config(credentials=PasswordCredentials(**creds)))


def test_password_login_happens_once(api: respx.MockRouter) -> None:
    login = api.post("/v1/login").mock(return_value=login_ok("s1"))
    devices = api.get("/v1/devices/id/1").mock(return_value=httpx.Response(200, json={"id": "1"}))
    with password_client(enterprise="acme") as zc:
        zc.nodes.get_edge_node("1")
        zc.nodes.get_edge_node("1")
        assert zc.token == "s1"
    assert login.call_count == 1
    assert json.loads(login.calls.last.request.content) == {
        "password": "pw",
        "usernameAtRealm": "me@example.com",
        "enterpriseName": "acme",
    }
    assert all(c.request.headers["Authorization"] == "Bearer s1" for c in devices.calls)


def test_realm_login_payload(api: respx.MockRouter) -> None:
    login = api.post("/v1/login").mock(return_value=login_ok("s1"))
    api.get("/v1/devices/id/1").mock(return_value=httpx.Response(200, json={}))
    with password_client(realm="corp") as zc:
        zc.nodes.get_edge_node("1")
    sent = json.loads(login.calls.last.request.content)
    assert sent == {"password": "pw", "username": "me@example.com", "realm": "corp"}


def test_expired_session_relogs_in_once(api: respx.MockRouter) -> None:
    login = api.post("/v1/login").mock(side_effect=[login_ok("old"), login_ok("new")])
    devices = api.get("/v1/devices/id/1").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"id": "1"})]
    )
    with password_client() as zc:
        assert zc.nodes.get_edge_node("1").id == "1"
    assert login.call_count == 2
    assert [c.request.headers["Authorization"] for c in devices.calls] == [
        "Bearer old",
        "Bearer new",
    ]


def test_persistent_401_is_raised_after_one_relogin(api: respx.MockRouter) -> None:
    login = api.post("/v1/login").mock(return_value=login_ok("s"))
    api.get("/v1/devices/id/1").mock(return_value=httpx.Response(401))
    with password_client() as zc, pytest.raises(AuthenticationError):
        zc.nodes.get_edge_node("1")
    assert login.call_count == 2


def test_rejected_login_raises_with_cause(api: respx.MockRouter) -> None:
    api.post("/v1/login").mock(
        return_value=httpx.Response(
            401, json={"cause": "CREDENTIAL_MISMATCH", "noOfLoginAttemptsLeft": 2}
        )
    )
    with password_client() as zc, pytest.raises(AuthenticationError, match="CREDENTIAL_MISMATCH"):
        zc.nodes.get_edge_node("1")


def test_token_credentials_do_not_login(client: ZedcloudClient, api: respx.MockRouter) -> None:
    login = api.post("/v1/login")
    api.get("/v1/devices/id/1").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthenticationError):
        client.nodes.get_edge_node("1")
    assert not login.called


def test_explicit_api_key_for_kubernetes(api: respx.MockRouter) -> None:
    route = api.get("/v1/cluster/instances/kubernetes/c1/kubeconfig").mock(
        return_value=httpx.Response(200, json={})
    )
    with ZedcloudClient(config=make_config(api_key="k8s-key")) as zc:
        zc.k8s.get_dashboard_kubeconfig("c1")
    assert route.calls.last.request.headers["X-API-KEY"] == "k8s-key"


def test_secrets_are_not_in_reprs() -> None:
    zc = password_client(password="hunter2-secret")
    assert "hunter2-secret" not in repr(zc.config)
    assert "tok-secret-value" not in repr(
        make_config(credentials=TokenCredentials("tok-secret-value"))
    )
