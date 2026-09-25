"""Edge node service with name-or-ID helpers and state waiters."""

from __future__ import annotations

from collections.abc import Collection

from zedcloud._generated.models import DeviceStatusMsg, RunState, Tag
from zedcloud._generated.services.nodes import AsyncNodesService as _AsyncNodesService
from zedcloud._generated.services.nodes import NodesService as _NodesService
from zedcloud.waiters import async_wait_until, state_in, wait_until

NODE_FAILURE_STATES = (RunState.RUN_STATE_SUSPECT,)


class NodesService(_NodesService):
    """Edge nodes, projects, hardware models and brands."""

    def lookup_project(self, name_or_id: str, *, request_id: str | None = None) -> Tag:
        """Get a project by name or ID (projects are "resource groups" in the API)."""
        return self.lookup_resource_group(name_or_id, request_id=request_id)

    def wait_for_edge_node(
        self,
        name_or_id: str,
        states: Collection[RunState | str] = (RunState.RUN_STATE_ONLINE,),
        *,
        fail_states: Collection[RunState | str] = (),
        timeout: float = 900.0,
        interval: float = 10.0,
    ) -> DeviceStatusMsg:
        """Poll an edge node's status until its ``run_state`` is one of ``states``.

        Example: after ``reboot(id)``, ``wait_for_edge_node(id)`` returns once it is
        back online. Pass ``fail_states`` to stop early on states you consider fatal.
        """
        return wait_until(
            lambda: self.lookup_edge_node_status(name_or_id),
            state_in("run_state", states),
            failed=state_in("run_state", fail_states) if fail_states else None,
            timeout=timeout,
            interval=interval,
            description=f"edge node {name_or_id} to reach {_names(states)}",
        )


class AsyncNodesService(_AsyncNodesService):
    """Edge nodes, projects, hardware models and brands (async)."""

    async def lookup_project(self, name_or_id: str, *, request_id: str | None = None) -> Tag:
        """Get a project by name or ID (projects are "resource groups" in the API)."""
        return await self.lookup_resource_group(name_or_id, request_id=request_id)

    async def wait_for_edge_node(
        self,
        name_or_id: str,
        states: Collection[RunState | str] = (RunState.RUN_STATE_ONLINE,),
        *,
        fail_states: Collection[RunState | str] = (),
        timeout: float = 900.0,
        interval: float = 10.0,
    ) -> DeviceStatusMsg:
        """Poll an edge node's status until its ``run_state`` is one of ``states``."""
        return await async_wait_until(
            lambda: self.lookup_edge_node_status(name_or_id),
            state_in("run_state", states),
            failed=state_in("run_state", fail_states) if fail_states else None,
            timeout=timeout,
            interval=interval,
            description=f"edge node {name_or_id} to reach {_names(states)}",
        )


def _names(states: Collection[object]) -> str:
    return "/".join(str(getattr(s, "value", s)) for s in states)
