"""Database integration service for the servers domain.

Moved from `app/services/database_integration.py` under #228 PR 2d and
rewritten on top of `ServersUnitOfWork` / `ServerRepository` (R-15).

The legacy implementation talked to SQLAlchemy directly via
`SessionLocal()` + `session.query(Server)` and registered a *sync*
callback with `MinecraftServerManager`. After Issue #280 the
`MinecraftServerManager._notify_status_change` callsites are all
async-aware and await the registered callback directly, so the
canonical contract is now async:

* `_update_server_status_async(server_id, status)` is the async impl
  registered with the manager via `set_status_update_callback`. The
  manager `await`s it from each of its ``async def`` callsites,
  restoring the bool result that the PR #279 fire-and-forget bridge
  dropped and preserving ordering of consecutive status changes
  within each task.
* `update_server_status_sync(server_id, status)` is preserved as a
  cross-thread façade: it captures the running event loop in
  `initialize()` and dispatches via `asyncio.run_coroutine_threadsafe`
  for daemon callers that still cannot `await` (subprocess SIGCHLD
  reapers, threadpool callbacks). The same-loop branch keeps its
  fire-and-forget semantics for the same reason — calling
  `future.result()` on the loop you're already running on would
  deadlock — but the manager no longer takes that branch since it now
  awaits the async method directly.
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


# `MinecraftServerManager.set_status_update_callback` accepts either a
# sync `(server_id, status) -> bool` or an async
# `(server_id, status) -> Awaitable[bool]` callable. Since #280 we
# register the async impl so each manager callsite awaits a real
# bool result.
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

        Since #280 the registered callback is the *async* impl: each
        `MinecraftServerManager._notify_status_change` callsite awaits
        it directly, so the bool result (and ordering of consecutive
        status changes within a task) propagate back to the manager.
        Cross-thread callers can still use `update_server_status_sync`
        explicitly when they need the bridge.
        """
        self._loop = asyncio.get_running_loop()
        minecraft_server_manager.set_status_update_callback(
            self._update_server_status_async
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
                # Single-query fetch of every non-deleted server using the
                # port=None / statuses=<all> overload (N3 optimisation —
                # replaces the legacy per-status loop which issued one
                # query per ``ServerStatus`` member).
                all_servers: List[ServerEntity] = await uow.servers.list_by_port(
                    port=None,
                    statuses=list(ServerStatus),
                    include_deleted=False,
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
        return ``True`` as a best-effort signal. Cross-thread callers
        block on the future's result.

        Raises ``RuntimeError`` if the service has not been initialised
        (loop never captured). The legacy ``asyncio.run(coro)`` fallback
        was removed because it crashes with ``RuntimeError: asyncio.run()
        cannot be called from a running event loop`` whenever invoked
        from an async caller (e.g. FastAPI request handlers) — exactly
        the conditions this bridge was added to support. Callers that
        need a private loop should instantiate their own service.
        """
        loop = self._loop
        if loop is None:
            raise RuntimeError(
                f"{self.__class__.__name__} not initialised; "
                "call initialize() before sync entry points"
            )
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


class _ServiceHolder:
    """Process-wide holder for the lifecycle-aware ``DatabaseIntegrationService``.

    Mirrors ``app/backups/__init__.py::backup_scheduler_instance`` (introduced
    in PR #264). The FastAPI lifespan
    (``app/main.py::_initialize_database_integration``) constructs the
    service via :func:`make_database_integration_service`, runs
    ``initialize()`` (which captures the running event loop for the
    sync→async bridge), then publishes the instance via ``set()``.
    Module-level callers — most importantly the legacy shim at
    ``app/services/database_integration.py`` — resolve through ``get()``
    at access time, so they always see the lifespan-built singleton
    rather than a stale import-time instance bound before the loop was
    available.
    """

    def __init__(self) -> None:
        self._instance: Optional[DatabaseIntegrationService] = None

    def set(self, instance: DatabaseIntegrationService) -> None:
        self._instance = instance

    def get(self) -> DatabaseIntegrationService:
        if self._instance is None:
            raise RuntimeError(
                "database_integration_service is not initialised; "
                "FastAPI lifespan startup must complete first."
            )
        return self._instance

    def clear(self) -> None:
        """Reset to the un-initialised state (lifespan partial-failure / test helper)."""
        self._instance = None

    def is_set(self) -> bool:
        return self._instance is not None


database_integration_instance = _ServiceHolder()


def make_database_integration_service() -> DatabaseIntegrationService:
    """Factory wired from `app/main.py` lifespan."""
    from app.servers.api.dependencies import make_servers_uow_from_session_factory

    return DatabaseIntegrationService(uow_factory=make_servers_uow_from_session_factory)


def __getattr__(name: str) -> Any:
    """Lazy resolver for the legacy ``database_integration_service`` name.

    Returning the holder's current instance on attribute access lets test
    code that still imports the symbol (e.g. ``test_database_integration_enhanced``)
    keep working, while ensuring access happens *after* the lifespan has
    initialised the singleton. Raises ``RuntimeError`` (via the holder)
    if accessed pre-init — a clear error rather than the silent
    ``RuntimeError: asyncio.run() cannot be called from a running event
    loop`` failure that the old import-time instance produced when its
    captured loop never existed.
    """
    if name == "database_integration_service":
        return database_integration_instance.get()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ``database_integration_service`` is resolved lazily via __getattr__
# (PEP 562); ruff's F822 cannot see PEP-562 names so it is suppressed.
__all__ = [  # noqa: F822
    "DatabaseIntegrationService",
    "StatusUpdateCallback",
    "UowFactory",
    "database_integration_instance",
    "database_integration_service",
    "make_database_integration_service",
]
