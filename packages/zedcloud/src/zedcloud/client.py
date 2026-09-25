"""Zedcloud API clients (sync and async)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from zedcloud._transport import AsyncTransport, SyncTransport
from zedcloud.config import ZedcloudConfig, resolve_config
from zedcloud.operations import Operation, get_operation, model_for
from zedcloud.services import (
    AppProfilesService,
    AppsService,
    AsyncAppProfilesService,
    AsyncAppsService,
    AsyncDiagService,
    AsyncIamService,
    AsyncJobsService,
    AsyncK8sService,
    AsyncNetworksService,
    AsyncNodeClustersService,
    AsyncNodesService,
    AsyncOrchestrationService,
    AsyncStorageService,
    DiagService,
    IamService,
    JobsService,
    K8sService,
    NetworksService,
    NodeClustersService,
    NodesService,
    OrchestrationService,
    StorageService,
)


def _config_from_args(config: ZedcloudConfig | None, kwargs: dict[str, Any]) -> ZedcloudConfig:
    given = {k: v for k, v in kwargs.items() if v is not None}
    if config is not None:
        if given:
            raise ValueError("pass either config= or connection keyword arguments, not both")
        return config
    return resolve_config(**given)


def _prepare_call(
    op: Operation,
    path: Mapping[str, Any] | None,
    query: Mapping[str, Any] | None,
    body: Any,
    headers: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate and normalise arguments for a registry-driven call.

    Parameters may be given by wire name (``next.pageSize``) or Python name
    (``page_size``). Unknown names are rejected rather than silently ignored.
    """

    def normalise(given: Mapping[str, Any] | None, allowed: tuple[Any, ...], kind: str) -> dict:
        by_name = {p.name: p.name for p in allowed} | {p.python_name: p.name for p in allowed}
        out: dict[str, Any] = {}
        for key, value in (given or {}).items():
            if key not in by_name:
                names = ", ".join(p.name for p in allowed) or "none"
                raise ValueError(
                    f"{op.operation_id}: unknown {kind} parameter {key!r} (valid: {names})"
                )
            out[by_name[key]] = value
        return out

    path_values = normalise(path, op.path_params, "path")
    missing = [p.name for p in op.path_params if p.name not in path_values]
    if missing:
        raise ValueError(f"{op.operation_id}: missing path parameters {missing}")
    query_values = normalise(query, op.query_params, "query")
    missing_q = [p.name for p in op.query_params if p.required and p.name not in query_values]
    if missing_q:
        raise ValueError(f"{op.operation_id}: missing required query parameters {missing_q}")
    if body is not None and not op.has_body:
        raise ValueError(f"{op.operation_id} does not take a request body")
    body_model = model_for(op.body_model)
    if body_model is not None and isinstance(body, Mapping):
        # Accept snake_case or camelCase keys; unknown keys pass through untouched.
        body = body_model.model_validate(dict(body))
    return {
        "path": path_values,
        "multi_segment": {p.name for p in op.path_params if p.multi_segment},
        "query": query_values,
        "headers": normalise(headers, op.header_params, "header"),
        "body": body,
        "response_model": model_for(op.response_model),
        "operation_id": op.operation_id,
    }


class ZedcloudClient:
    """Synchronous client for one Zedcloud tenant.

    Construct from explicit settings, a named profile, or the environment::

        ZedcloudClient(base_url="https://zedcontrol.zededa.net", token="…")
        ZedcloudClient(base_url=…, username="me@example.com", password="…", enterprise="acme")
        ZedcloudClient.from_profile("acme-prod")
        ZedcloudClient()                   # ZEDCLOUD_PROFILE or ZEDCLOUD_* variables

    Namespaces mirror the Zedcloud services: ``apps``, ``app_profiles``,
    ``diag``, ``iam``, ``jobs``, ``k8s``, ``networks``, ``node_clusters``,
    ``nodes`` (edge nodes, projects, hardware models), ``orchestration``,
    ``storage``. Use as a context manager, or call :meth:`close`.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        enterprise: str | None = None,
        realm: str | None = None,
        api_key: str | None = None,
        profile: str | None = None,
        config_path: Path | str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        verify: bool | str | None = None,
        config: ZedcloudConfig | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = _config_from_args(
            config,
            {
                "base_url": base_url,
                "token": token,
                "username": username,
                "password": password,
                "enterprise": enterprise,
                "realm": realm,
                "api_key": api_key,
                "profile": profile,
                "config_path": config_path,
                "timeout": timeout,
                "max_retries": max_retries,
                "verify": verify,
            },
        )
        self._transport = SyncTransport(self.config, http_client)
        t = self._transport
        self.apps = AppsService(t)
        self.app_profiles = AppProfilesService(t)
        self.diag = DiagService(t)
        self.iam = IamService(t)
        self.jobs = JobsService(t)
        self.k8s = K8sService(t)
        self.networks = NetworksService(t)
        self.node_clusters = NodeClustersService(t)
        self.nodes = NodesService(t)
        self.orchestration = OrchestrationService(t)
        self.storage = StorageService(t)

    @classmethod
    def from_profile(cls, name: str | None = None, **kwargs: Any) -> ZedcloudClient:
        """Connect using a profile from the profiles file (default profile if ``name`` is None)."""
        from zedcloud.config import get_profile

        return cls(config=get_profile(name, kwargs.pop("config_path", None)).resolve(**kwargs))

    @classmethod
    def from_env(cls, **kwargs: Any) -> ZedcloudClient:
        """Connect using ``ZEDCLOUD_*`` environment variables (or ``ZEDCLOUD_PROFILE``)."""
        return cls(**kwargs)

    @property
    def token(self) -> str | None:
        """Current session token (after login, for password credentials)."""
        return self._transport.auth.token

    def request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> Any:
        """Send a raw request to a path under ``/api`` (e.g. ``/v1/devices``). Returns JSON."""
        return self._transport.request(
            method,
            path,
            path=path_params,
            query=query,
            body=body,
            headers=headers,
            request_id=request_id,
        )

    def call(
        self,
        operation_id: str,
        *,
        path: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> Any:
        """Invoke any operation by operationId (or ``service.method_name``).

        Parameters are validated against the registry in :mod:`zedcloud.operations`.
        """
        op = get_operation(operation_id)
        service = getattr(self, op.service)
        prepared = _prepare_call(op, path, query, body, headers)
        return service._request(op.http_method, op.path, request_id=request_id, **prepared)

    def whoami(self) -> Any:
        """The current session: user, enterprise, and role. Useful to confirm the tenant."""
        return self.iam.get_user_session_self()

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> ZedcloudClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"ZedcloudClient({self.config.label!r})"


class AsyncZedcloudClient:
    """Asynchronous client for one Zedcloud tenant.

    Same constructor and namespaces as :class:`ZedcloudClient`; every
    operation is a coroutine and ``iter_*`` methods are async iterators::

        async with AsyncZedcloudClient.from_profile("acme-prod") as zc:
            async for node in zc.nodes.iter_edge_nodes(project_name="plant-7"):
                print(node.name, node.run_state)
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        enterprise: str | None = None,
        realm: str | None = None,
        api_key: str | None = None,
        profile: str | None = None,
        config_path: Path | str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        verify: bool | str | None = None,
        config: ZedcloudConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = _config_from_args(
            config,
            {
                "base_url": base_url,
                "token": token,
                "username": username,
                "password": password,
                "enterprise": enterprise,
                "realm": realm,
                "api_key": api_key,
                "profile": profile,
                "config_path": config_path,
                "timeout": timeout,
                "max_retries": max_retries,
                "verify": verify,
            },
        )
        self._transport = AsyncTransport(self.config, http_client)
        t = self._transport
        self.apps = AsyncAppsService(t)
        self.app_profiles = AsyncAppProfilesService(t)
        self.diag = AsyncDiagService(t)
        self.iam = AsyncIamService(t)
        self.jobs = AsyncJobsService(t)
        self.k8s = AsyncK8sService(t)
        self.networks = AsyncNetworksService(t)
        self.node_clusters = AsyncNodeClustersService(t)
        self.nodes = AsyncNodesService(t)
        self.orchestration = AsyncOrchestrationService(t)
        self.storage = AsyncStorageService(t)

    @classmethod
    def from_profile(cls, name: str | None = None, **kwargs: Any) -> AsyncZedcloudClient:
        from zedcloud.config import get_profile

        return cls(config=get_profile(name, kwargs.pop("config_path", None)).resolve(**kwargs))

    @classmethod
    def from_env(cls, **kwargs: Any) -> AsyncZedcloudClient:
        return cls(**kwargs)

    @property
    def token(self) -> str | None:
        return self._transport.auth.token

    async def request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> Any:
        return await self._transport.request(
            method,
            path,
            path=path_params,
            query=query,
            body=body,
            headers=headers,
            request_id=request_id,
        )

    async def call(
        self,
        operation_id: str,
        *,
        path: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> Any:
        op = get_operation(operation_id)
        service = getattr(self, op.service)
        prepared = _prepare_call(op, path, query, body, headers)
        return await service._request(op.http_method, op.path, request_id=request_id, **prepared)

    async def whoami(self) -> Any:
        return await self.iam.get_user_session_self()

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> AsyncZedcloudClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"AsyncZedcloudClient({self.config.label!r})"
