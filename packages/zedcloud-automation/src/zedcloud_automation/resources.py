"""Resource lifecycle helpers for create → use → cleanup patterns."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from zedcloud import ZedcloudClient


@dataclass
class ManagedResource:
    """A resource with an optional cleanup callback."""

    kind: str
    resource_id: str
    name: str | None = None
    raw: Any = None
    delete: Callable[[], None] | None = None


@dataclass
class ResourceTracker:
    """Collects resources created during a test and deletes them in reverse order."""

    client: ZedcloudClient
    _resources: list[ManagedResource] = field(default_factory=list)

    def track(self, resource: ManagedResource) -> ManagedResource:
        self._resources.append(resource)
        return resource

    def add(
        self,
        kind: str,
        resource_id: str,
        *,
        name: str | None = None,
        raw: Any = None,
        delete: Callable[[], None] | None = None,
    ) -> ManagedResource:
        return self.track(
            ManagedResource(
                kind=kind,
                resource_id=resource_id,
                name=name,
                raw=raw,
                delete=delete,
            )
        )

    def cleanup(self) -> None:
        errors: list[str] = []
        while self._resources:
            resource = self._resources.pop()
            if resource.delete is None:
                continue
            try:
                resource.delete()
            except Exception as exc:  # noqa: BLE001 — collect all cleanup failures
                errors.append(f"{resource.kind}/{resource.resource_id}: {exc}")
        if errors:
            raise RuntimeError("resource cleanup failed:\n" + "\n".join(errors))
