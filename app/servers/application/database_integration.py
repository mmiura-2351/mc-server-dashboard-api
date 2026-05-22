"""Database integration service for the servers domain.

Moved from `app/services/database_integration.py` under #228 PR 2d and
rewritten on top of `ServersUnitOfWork` / `ServerRepository` (R-15).

The legacy implementation talked to SQLAlchemy directly via
`SessionLocal()` + `session.query(Server)` and registered a *sync*
callback with `MinecraftServerManager`. That contract still holds
on the daemon side — subprocess SIGCHLD reapers and threadpool callbacks
cannot `await` — so this module owns the sync→async bridge:

* `update_server_status_sync(server_id, status)` is the public
  cross-thread entry point. It captures the running event loop in
  `initialize()` and dispatches each call via
  `asyncio.run_coroutine_threadsafe` to that loop.
* The async impl runs under `ServersUnitOfWork`. Repository
  `update_status` owns its own transaction (see D-5 in the #228 plan)
  so `commit()` is a no-op for that path — the UoW context is still
  used so future cross-write operations can land here without changing
  the call site.

A small backward-compat alias `update_server_status` is kept so legacy
callers and tests can keep dotting through the same name.

For batch / read helpers (`sync_server_states`, `is_server_running`,
etc.) we mirror the legacy API surface — those are consumed by
`app/servers/routers/{control,utilities}.py` and a handful of integration
tests. They now run through the Repository as well.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from app.servers.application.minecraft_server import minecraft_server_manager
from app.servers.domain.entities import ServerEntity
from app.servers.domain.ports import ServersUnitOfWork
from app.servers.models import ServerStatus

logger = logging.getLogger(__name__)


# A sync `(server_id, status) -> bool` callback contract is what
# `MinecraftServerManager.set_status_update_callback` accepts.
StatusUpdateCallback = Callable[[int, ServerStatus], bool]
UowFactory = Callable[[], ServersUnitOfWork]


class DatabaseIntegrationService:
    """Bridge between `MinecraftServerManager` callbacks and the repository.

    Constructed once at lifespan via `make_database_integration_service()`
    so the `uow_factory` resolves to `make_servers_uow_from_session_factory`
    (which opens / closes its own session per call — the same pattern the
    backup scheduler uses).
    """

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ----- Lifecycle -----

    def initialize(self) -> None:
        """Capture the running event loop and register the status callback.

        Must be called from inside the loop that will own the bridge.
        """
        self._loop = asyncio.get_running_loop()
        minecraft_server_manager.set_status_update_callback(
            self.update_server_status_sync
        )
        logger.info("Database integration initialized")

    # ----- Status updates (sync→async bridge) -----

    def update_server_status_sync(self, server_id: int, status: ServerStatus) -> bool:
        """Sync entry point for daemon callbacks.

        Bridges to async via `asyncio.run_coroutine_threadsafe`. **Safe to
        call from threads other than the main event loop** (subprocess
        SIGCHLD reaper, threadpool callbacks). When invoked from inside
        the loop thread itself (the common case — `_notify_status_change`
        is called from monitor coroutines on the same loop), we schedule
        the async update as a fire-and-forget task to avoid the deadlock
        that `future.result()` would otherwise cause.
        """
        loop = self._loop
        if loop is None:
            logger.warning(
                "update_server_status_sync called before initialize(); "
                "dropping update for server %s -> %s",
                server_id,
                status,
            )
            return False
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            # Same-loop call path: schedule the async update as a
            # fire-and-forget task. Optimistically returns True; the
            # async impl logs its own errors.
            asyncio.ensure_future(
                self._update_server_status_async(server_id, status), loop=loop
            )
            return True
        # Cross-thread path: bridge via run_coroutine_threadsafe.
        future = asyncio.run_coroutine_threadsafe(
            self._update_server_status_async(server_id, status), loop
        )
        try:
            return future.result(timeout=10.0)
        except Exception as exc:
            logger.error(
                "update_server_status_sync error for server %s: %s",
                server_id,
                exc,
            )
            return False

    # Backward-compat alias: legacy callers / tests use `update_server_status`.
    update_server_status = update_server_status_sync

    async def _update_server_status_async(
        self, server_id: int, status: ServerStatus
    ) -> bool:
        """Async impl — runs `ServerRepository.update_status` under UoW."""
        try:
            async with self._uow_factory() as uow:
                entity = await uow.servers.update_status(server_id, status)
                if entity is None:
                    logger.warning("Server %s not found for status update", server_id)
                    return False
                # `update_status` owns its own transaction (D-5), so
                # commit here is a no-op but kept for symmetry with the
                # UoW contract.
                await uow.commit()
                return True
        except Exception as exc:
            logger.error(
                "Unexpected error updating server %s status: %s",
                server_id,
                exc,
                exc_info=True,
            )
            return False

    # ----- Read / batch helpers (legacy surface preserved) -----

    async def sync_server_states_with_restore(self) -> bool:
        """Restore PID-file processes then reconcile DB rows.

        Mirrors the legacy method: first ask the manager to re-attach to
        running subprocesses, then call `sync_server_states_async`.
        """
        try:
            logger.info(
                "Starting enhanced server state synchronization "
                "with process restoration..."
            )
            restoration_results = (
                await minecraft_server_manager.discover_and_restore_processes()
            )
            if restoration_results:
                restored = sum(1 for v in restoration_results.values() if v)
                logger.info(
                    "Process restoration completed: %s/%s servers restored",
                    restored,
                    len(restoration_results),
                )
            sync_ok = await self.sync_server_states_async()
            if sync_ok:
                logger.info(
                    "Enhanced server state synchronization completed successfully"
                )
            else:
                logger.warning(
                    "Enhanced server state synchronization completed with errors"
                )
            return sync_ok
        except Exception as exc:
            logger.error(
                "Error during enhanced server state synchronization: %s",
                exc,
                exc_info=True,
            )
            return False

    async def sync_server_states_async(self) -> bool:
        """Reconcile DB row statuses with the manager's view of running pids."""
        try:
            running_ids = set(minecraft_server_manager.list_running_servers())
            updates: Dict[int, ServerStatus] = {}
            async with self._uow_factory() as uow:
                # The repository does not currently expose a "list all
                # non-deleted" method — iterate by status. This matches
                # the legacy `Server.is_deleted.is_(False)` query.
                all_servers: List[ServerEntity] = []
                for status in ServerStatus:
                    all_servers.extend(
                        await uow.servers.list_by_status(status, include_deleted=False)
                    )
                for srv in all_servers:
                    is_running = srv.id in running_ids
                    if is_running and srv.status in (
                        ServerStatus.stopped,
                        ServerStatus.error,
                    ):
                        logger.info(
                            "Correcting server %s status: %s -> running",
                            srv.id,
                            srv.status,
                        )
                        updates[srv.id] = ServerStatus.running
                    elif not is_running and srv.status in (
                        ServerStatus.starting,
                        ServerStatus.running,
                        ServerStatus.stopping,
                    ):
                        logger.info(
                            "Correcting server %s status: %s -> stopped",
                            srv.id,
                            srv.status,
                        )
                        updates[srv.id] = ServerStatus.stopped
                if updates:
                    logger.info("Updating %s server statuses", len(updates))
                    await uow.servers.batch_update_statuses(updates)
                else:
                    logger.info("Server state synchronization completed")
            return True
        except Exception as exc:
            logger.error("Unexpected error syncing server states: %s", exc, exc_info=True)
            return False

    def sync_server_states(self) -> bool:
        """Sync wrapper for `sync_server_states_async` (legacy callers).

        Routers like `app/servers/routers/utilities.py` still invoke this
        as a sync function. We bridge through the captured loop the same
        way `update_server_status_sync` does.
        """
        return bool(self._run_sync(self.sync_server_states_async()))

    async def batch_update_server_statuses_async(
        self, status_updates: Dict[int, ServerStatus]
    ) -> Dict[int, bool]:
        if not status_updates:
            return {}
        try:
            async with self._uow_factory() as uow:
                results = await uow.servers.batch_update_statuses(status_updates)
            out: Dict[int, bool] = {}
            for sid in status_updates:
                out[sid] = results.get(sid) is not None
                if out[sid]:
                    logger.info("Batch update: server %s -> %s", sid, status_updates[sid])
                else:
                    logger.warning("Batch update: server %s not found", sid)
            return out
        except Exception as exc:
            logger.error("Unexpected error in batch update: %s", exc, exc_info=True)
            return {sid: False for sid in status_updates}

    def batch_update_server_statuses(
        self, status_updates: Dict[int, ServerStatus]
    ) -> Dict[int, bool]:
        result = self._run_sync(self.batch_update_server_statuses_async(status_updates))
        if isinstance(result, dict):
            return result
        return {sid: False for sid in status_updates}

    def get_server_process_info(self, server_id: int) -> Optional[dict]:
        return minecraft_server_manager.get_server_info(server_id)

    def is_server_running(self, server_id: int) -> bool:
        return server_id in minecraft_server_manager.list_running_servers()

    def get_all_running_servers(self) -> List[int]:
        return minecraft_server_manager.list_running_servers()

    async def get_servers_by_status_async(
        self, status: ServerStatus
    ) -> List[ServerEntity]:
        try:
            async with self._uow_factory() as uow:
                return await uow.servers.list_by_status(status, include_deleted=False)
        except Exception as exc:
            logger.error(
                "Failed to get servers by status %s: %s", status, exc, exc_info=True
            )
            return []

    def get_servers_by_status(self, status: ServerStatus) -> List[ServerEntity]:
        result = self._run_sync(self.get_servers_by_status_async(status))
        if isinstance(result, list):
            return result
        return []

    # ----- Internal -----

    def _run_sync(self, coro: Any) -> object:
        """Run `coro` on the captured loop, blocking if cross-thread.

        Same semantics as `update_server_status_sync`: if we are already
        on the loop thread, schedule the coroutine (non-blocking) and
        return True as a best-effort signal. Cross-thread callers block
        on the future's result.
        """
        loop = self._loop
        if loop is None:
            # Fall back to running the coroutine in a private loop. This
            # path is mostly hit by tests that don't go through the
            # lifespan and just instantiate the service directly.
            return asyncio.run(coro)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            asyncio.ensure_future(coro, loop=loop)
            return True
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=30.0)
        except Exception as exc:
            logger.error("_run_sync error: %s", exc, exc_info=True)
            return False


# Module-level singleton (legacy compat). Initialised at import time so
# legacy `from app.services.database_integration import
# database_integration_service` (re-exported via the shim) still
# resolves. The lifespan calls `initialize()` to capture the loop and
# wire the callback.
database_integration_service: "DatabaseIntegrationService"


def make_database_integration_service() -> DatabaseIntegrationService:
    """Factory wired from `app/main.py` lifespan."""
    from app.servers.api.dependencies import make_servers_uow_from_session_factory

    return DatabaseIntegrationService(uow_factory=make_servers_uow_from_session_factory)


database_integration_service = make_database_integration_service()


__all__ = [
    "DatabaseIntegrationService",
    "StatusUpdateCallback",
    "UowFactory",
    "database_integration_service",
    "make_database_integration_service",
]
