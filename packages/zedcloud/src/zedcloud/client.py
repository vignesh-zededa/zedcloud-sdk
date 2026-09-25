"""High-level Zedcloud API client."""

from __future__ import annotations

from types import TracebackType
from typing import Self

import httpx

from zedcloud.auth import api_key_headers, bearer_headers
from zedcloud.config import ZedcloudConfig
from zedcloud.http import HttpTransport
from zedcloud.services.app_profiles import AppProfilesService
from zedcloud.services.apps import AppsService
from zedcloud.services.diag import DiagService
from zedcloud.services.iam import IamService
from zedcloud.services.jobs import JobsService
from zedcloud.services.k8s import K8sService
from zedcloud.services.networks import NetworksService
from zedcloud.services.node_clusters import NodeClustersService
from zedcloud.services.nodes import NodesService
from zedcloud.services.orchestration import OrchestrationService
from zedcloud.services.storage import StorageService


class ZedcloudClient:
    """Synchronous client for ZEDEDA Zedcloud REST APIs.

    Service namespaces mirror the OpenAPI specs committed under ``openapi/``:

    * ``apps`` — Edge Application
    * ``nodes`` — Edge Node
    * ``networks`` — Edge Network
    * ``iam`` — Identity & Access Management
    * ``k8s`` — Kubernetes / ZKS (ApiKeyAuth)
    * ``storage`` — Images / datastores / volumes
    * ``jobs`` — Asynchronous bulk jobs
    * ``orchestration`` — Cluster orchestration
    * ``diag`` — Diagnostics
    * ``app_profiles`` — App profiles / asset groups
    * ``node_clusters`` — Edge-node clusters

    Example::

        from zedcloud import ZedcloudClient

        with ZedcloudClient.from_env() as client:
            apps = client.apps.query_edge_application_bundles(next_page_size=10)
            print(len(apps.list or []))
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        config: ZedcloudConfig | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if config is None:
            config = ZedcloudConfig.from_env(
                base_url=base_url,
                token=token,
                api_key=api_key,
                timeout=timeout,
                max_retries=max_retries,
            )
        elif base_url or token or api_key is not None:
            msg = "Pass either config= or base_url/token kwargs, not both"
            raise ValueError(msg)
        self.config = config

        shared_client = http_client or httpx.Client(timeout=config.timeout)
        self._owns_http_client = http_client is None
        self._http_client = shared_client

        bearer = HttpTransport(
            api_root=config.api_root,
            default_headers=bearer_headers(config),
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            client=shared_client,
        )
        # Kubernetes service uses ApiKeyAuth; keep a dedicated transport.
        api_key_transport = HttpTransport(
            api_root=config.api_root,
            default_headers=api_key_headers(config),
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            client=shared_client,
        )
        # Prevent nested transports from closing the shared httpx client.
        bearer._owns_client = False
        api_key_transport._owns_client = False
        self._bearer = bearer
        self._api_key = api_key_transport

        self.apps = AppsService(bearer)
        self.nodes = NodesService(bearer)
        self.networks = NetworksService(bearer)
        self.iam = IamService(bearer)
        self.storage = StorageService(bearer)
        self.jobs = JobsService(bearer)
        self.orchestration = OrchestrationService(bearer)
        self.diag = DiagService(bearer)
        self.app_profiles = AppProfilesService(bearer)
        self.node_clusters = NodeClustersService(bearer)
        self.k8s = K8sService(api_key_transport)

    @classmethod
    def from_env(cls, **kwargs: object) -> ZedcloudClient:
        """Construct a client using ``ZEDCLOUD_BASE_URL`` / ``ZEDCLOUD_TOKEN``."""
        return cls(**kwargs)  # type: ignore[arg-type]

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"ZedcloudClient(base_url={self.config.base_url!r})"
