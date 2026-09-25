"""Edge application service with state waiters."""

from __future__ import annotations

from collections.abc import Collection

from zedcloud._generated.models import AppInstStatusMsg, RunState
from zedcloud._generated.services.apps import AppsService as _AppsService
from zedcloud._generated.services.apps import AsyncAppsService as _AsyncAppsService
from zedcloud.services.nodes import _names
from zedcloud.waiters import async_wait_until, state_in, wait_until

APP_FAILURE_STATES = (RunState.RUN_STATE_ERROR,)


class AppsService(_AppsService):
    """Edge application bundles and instances."""

    def wait_for_app_instance(
        self,
        name_or_id: str,
        states: Collection[RunState | str] = (RunState.RUN_STATE_ONLINE,),
        *,
        fail_states: Collection[RunState | str] = APP_FAILURE_STATES,
        timeout: float = 900.0,
        interval: float = 10.0,
    ) -> AppInstStatusMsg:
        """Poll an app instance until its ``run_state`` is one of ``states``.

        Raises :class:`~zedcloud.errors.WaitFailedError` if it enters a
        ``fail_states`` state (``RUN_STATE_ERROR`` by default) first.
        """
        return wait_until(
            lambda: self.lookup_edge_application_instance_status(name_or_id),
            state_in("run_state", states),
            failed=state_in("run_state", fail_states) if fail_states else None,
            timeout=timeout,
            interval=interval,
            description=f"app instance {name_or_id} to reach {_names(states)}",
        )


class AsyncAppsService(_AsyncAppsService):
    """Edge application bundles and instances (async)."""

    async def wait_for_app_instance(
        self,
        name_or_id: str,
        states: Collection[RunState | str] = (RunState.RUN_STATE_ONLINE,),
        *,
        fail_states: Collection[RunState | str] = APP_FAILURE_STATES,
        timeout: float = 900.0,
        interval: float = 10.0,
    ) -> AppInstStatusMsg:
        """Poll an app instance until its ``run_state`` is one of ``states``."""
        return await async_wait_until(
            lambda: self.lookup_edge_application_instance_status(name_or_id),
            state_in("run_state", states),
            failed=state_in("run_state", fail_states) if fail_states else None,
            timeout=timeout,
            interval=interval,
            description=f"app instance {name_or_id} to reach {_names(states)}",
        )
