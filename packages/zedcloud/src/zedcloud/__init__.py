"""Zedcloud Python SDK — typed client for ZEDEDA Zedcloud REST APIs."""

from zedcloud.client import ZedcloudClient
from zedcloud.config import ZedcloudConfig
from zedcloud.errors import (
    ApiError,
    AuthError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServerError,
)

__all__ = [
    "ApiError",
    "AuthError",
    "ConflictError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "ZedcloudClient",
    "ZedcloudConfig",
]

__version__ = "0.1.0"
