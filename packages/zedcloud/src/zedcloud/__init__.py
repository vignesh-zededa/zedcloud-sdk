"""Python SDK for the ZEDEDA Zedcloud API.

Quick start::

    from zedcloud import ZedcloudClient

    with ZedcloudClient.from_profile("acme-prod") as zc:
        for node in zc.nodes.iter_edge_nodes(project_name="plant-7"):
            print(node.name, node.run_state)
"""

from zedcloud._base import OpenEnum, ZedcloudModel
from zedcloud._version import __version__
from zedcloud.client import AsyncZedcloudClient, ZedcloudClient
from zedcloud.config import (
    PasswordCredentials,
    Profile,
    TokenCredentials,
    ZedcloudConfig,
    get_profile,
    load_profiles,
)
from zedcloud.errors import (
    ApiError,
    AuthenticationError,
    AuthError,
    BadRequestError,
    ConfigError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    PreconditionFailedError,
    RateLimitError,
    ServerError,
    TransportError,
    WaitTimeoutError,
    ZedcloudError,
)

__all__ = [
    "ApiError",
    "AsyncZedcloudClient",
    "AuthError",
    "AuthenticationError",
    "BadRequestError",
    "ConfigError",
    "ConflictError",
    "NotFoundError",
    "OpenEnum",
    "PasswordCredentials",
    "PermissionDeniedError",
    "PreconditionFailedError",
    "Profile",
    "RateLimitError",
    "ServerError",
    "TokenCredentials",
    "TransportError",
    "WaitTimeoutError",
    "ZedcloudClient",
    "ZedcloudConfig",
    "ZedcloudError",
    "ZedcloudModel",
    "__version__",
    "get_profile",
    "load_profiles",
]
