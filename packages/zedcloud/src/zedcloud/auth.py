"""Authentication for Zedcloud requests.

:class:`ZedcloudAuth` is an ``httpx.Auth`` flow, so the same logic serves the
sync and async clients:

* token credentials are sent as ``Authorization: Bearer <token>``;
* password credentials log in via ``POST /v1/login`` on first use and log in
  again once if a request comes back 401 (Zedcloud sessions expire after a
  few hours of inactivity);
* requests to ApiKeyAuth services (Kubernetes) also get ``X-API-KEY``, which
  defaults to the session token.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Generator
from typing import Any

import httpx

from zedcloud.config import Credentials, PasswordCredentials, TokenCredentials
from zedcloud.errors import AuthenticationError

API_KEY_EXTENSION = "zedcloud.api_key_auth"
LOGIN_PATH = "/v1/login"


class ZedcloudAuth(httpx.Auth):
    """Attach Zedcloud credentials to each request, logging in when needed."""

    requires_response_body = True

    def __init__(self, credentials: Credentials, *, api_root: str, api_key: str | None = None):
        self._credentials = credentials
        self._api_root = api_root.rstrip("/")
        self._api_key = api_key
        self._token: str | None = (
            credentials.token if isinstance(credentials, TokenCredentials) else None
        )
        self._lock = threading.Lock()
        self.session_info: dict[str, Any] | None = None

    @property
    def token(self) -> str | None:
        """The current session token (``None`` until a password login happens)."""
        return self._token

    @property
    def can_login(self) -> bool:
        return isinstance(self._credentials, PasswordCredentials)

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        if self._token is None and self.can_login:
            login_response = yield self._login_request()
            self._store_login(login_response)
        self._apply(request)
        response = yield request
        if (
            response.status_code == 401
            and self.can_login
            and request.url.path != self._login_url().path
        ):
            stale = self._token
            login_response = yield self._login_request()
            with self._lock:
                # Another request may already have refreshed the session.
                if self._token == stale:
                    self._store_login(login_response)
            self._apply(request)
            yield request

    def _apply(self, request: httpx.Request) -> None:
        if self._token:
            request.headers["Authorization"] = f"Bearer {self._token}"
        if request.extensions.get(API_KEY_EXTENSION):
            key = self._api_key or self._token
            if key:
                request.headers["X-API-KEY"] = key

    def _login_url(self) -> httpx.URL:
        return httpx.URL(self._api_root + LOGIN_PATH)

    def _login_request(self) -> httpx.Request:
        creds = self._credentials
        assert isinstance(creds, PasswordCredentials)
        payload: dict[str, Any] = {"password": creds.password}
        if creds.realm:
            payload.update(username=creds.username, realm=creds.realm)
        else:
            payload["usernameAtRealm"] = creds.username
        if creds.enterprise:
            payload["enterpriseName"] = creds.enterprise
        return httpx.Request(
            "POST",
            self._login_url(),
            json=payload,
            headers={"Accept": "application/json"},
        )

    def _store_login(self, response: httpx.Response) -> None:
        try:
            data = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        cause = data.get("cause") if isinstance(data, dict) else None
        token = ((data.get("token") or {}).get("base64")) if isinstance(data, dict) else None
        if response.status_code >= 400 or (cause not in (None, "OK")) or not token:
            username = getattr(self._credentials, "username", "?")
            reason = cause or f"HTTP {response.status_code}"
            raise AuthenticationError(
                f"login failed for {username}: {reason}",
                status_code=response.status_code,
                method="POST",
                url=str(response.request.url),
                body={k: v for k, v in data.items() if k != "token"}
                if isinstance(data, dict)
                else None,
            )
        self._token = token
        self.session_info = {
            "user_id": data.get("userId"),
            "expires": (data.get("token") or {}).get("expires"),
        }
