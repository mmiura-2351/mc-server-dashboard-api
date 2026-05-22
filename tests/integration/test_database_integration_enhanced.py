"""Tests for `DatabaseIntegrationService` after the #228 PR 2d migration.

The service was rewritten on top of `ServersUnitOfWork` /
`ServerRepository` so these tests exercise behaviour through an
in-memory `FakeServersUnitOfWork` rather than mocking SQLAlchemy
internals (`SessionLocal`, `with_transaction`, query chains) — the
legacy assertion style is no longer applicable.

The async path is the canonical one. `update_server_status_sync` and
`sync_server_states` are sync façades that bridge through the loop the
service captured in `initialize()`.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.servers.application.database_integration import (
    DatabaseIntegrationService,
    database_integration_service,
    make_database_integration_service,
)
from app.servers.models import ServerStatus
from tests.unit.servers.fakes import (
    FakeServersUnitOfWork,
    make_server_entity,
)


@pytest.fixture
def uow() -> FakeServersUnitOfWork:
    return FakeServersUnitOfWork()


@pytest.fixture
def service(uow: FakeServersUnitOfWork) -> DatabaseIntegrationService:
    """Service wired to a single shared `FakeServersUnitOfWork`."""
    return DatabaseIntegrationService(uow_factory=lambda: uow)


class TestLifecycle:
    """`initialize()` captures the loop and wires the status callback."""

    async def test_initialize_captures_loop_and_registers_callback(
        self, service: DatabaseIntegrationService
    ) -> None:
        with patch(
            "app.servers.application.database_integration.minecraft_server_manager"
        ) as mock_mgr:
            service.initialize()
            mock_mgr.set_status_update_callback.assert_called_once_with(
                service.update_server_status_sync
            )
        assert service._loop is not None  # captured running loop


class TestStatusUpdates:
    """`update_server_status_sync` and its async impl."""

    async def test_async_update_writes_via_repository(
        self,
        service: DatabaseIntegrationService,
        uow: FakeServersUnitOfWork,
    ) -> None:
        uow.servers.seed(make_server_entity(id=1, status=ServerStatus.stopped))
        ok = await service._update_server_status_async(1, ServerStatus.running)
        assert ok is True
        updated = await uow.servers.get(1)
        assert updated is not None
        assert updated.status is ServerStatus.running

    async def test_async_update_returns_false_when_missing(
        self, service: DatabaseIntegrationService
    ) -> None:
        ok = await service._update_server_status_async(999, ServerStatus.running)
        assert ok is False

    async def test_sync_facade_routes_through_same_loop_path(
        self,
        service: DatabaseIntegrationService,
        uow: FakeServersUnitOfWork,
    ) -> None:
        # Initialise inside the running loop so the same-loop branch fires.
        with patch(
            "app.servers.application.database_integration.minecraft_server_manager"
        ):
            service.initialize()
        uow.servers.seed(make_server_entity(id=2, status=ServerStatus.stopped))
        # Same-loop path returns True optimistically and schedules the async
        # task; we need to yield so it actually runs.
        result = service.update_server_status_sync(2, ServerStatus.running)
        assert result is True
        # Drain the event loop.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        updated = await uow.servers.get(2)
        assert updated is not None
        assert updated.status is ServerStatus.running

    def test_sync_facade_warns_before_initialize(
        self, service: DatabaseIntegrationService
    ) -> None:
        # `_loop` is None — call should log a warning and return False.
        assert service.update_server_status_sync(1, ServerStatus.running) is False

    def test_update_server_status_alias_present(
        self, service: DatabaseIntegrationService
    ) -> None:
        # Legacy callers / tests dot through `update_server_status`.
        assert (
            DatabaseIntegrationService.update_server_status
            is DatabaseIntegrationService.update_server_status_sync
        )


class TestSyncServerStates:
    """`sync_server_states_async` reconciles DB rows with manager view."""

    async def test_promotes_stopped_to_running_when_pid_alive(
        self,
        service: DatabaseIntegrationService,
        uow: FakeServersUnitOfWork,
    ) -> None:
        uow.servers.seed(make_server_entity(id=1, status=ServerStatus.stopped))
        uow.servers.seed(make_server_entity(id=2, status=ServerStatus.error))
        uow.servers.seed(make_server_entity(id=3, status=ServerStatus.running))
        with patch(
            "app.servers.application.database_integration.minecraft_server_manager"
        ) as mock_mgr:
            mock_mgr.list_running_servers.return_value = [1, 2, 3]
            ok = await service.sync_server_states_async()
        assert ok is True
        srv1 = await uow.servers.get(1)
        srv2 = await uow.servers.get(2)
        srv3 = await uow.servers.get(3)
        assert srv1 is not None and srv1.status is ServerStatus.running
        assert srv2 is not None and srv2.status is ServerStatus.running
        assert srv3 is not None and srv3.status is ServerStatus.running

    async def test_demotes_running_to_stopped_when_pid_gone(
        self,
        service: DatabaseIntegrationService,
        uow: FakeServersUnitOfWork,
    ) -> None:
        uow.servers.seed(make_server_entity(id=1, status=ServerStatus.running))
        uow.servers.seed(make_server_entity(id=2, status=ServerStatus.starting))
        uow.servers.seed(make_server_entity(id=3, status=ServerStatus.stopping))
        with patch(
            "app.servers.application.database_integration.minecraft_server_manager"
        ) as mock_mgr:
            mock_mgr.list_running_servers.return_value = []
            ok = await service.sync_server_states_async()
        assert ok is True
        for sid in (1, 2, 3):
            srv = await uow.servers.get(sid)
            assert srv is not None and srv.status is ServerStatus.stopped

    async def test_no_changes_when_states_consistent(
        self,
        service: DatabaseIntegrationService,
        uow: FakeServersUnitOfWork,
    ) -> None:
        uow.servers.seed(make_server_entity(id=1, status=ServerStatus.running))
        uow.servers.seed(make_server_entity(id=2, status=ServerStatus.stopped))
        with patch(
            "app.servers.application.database_integration.minecraft_server_manager"
        ) as mock_mgr:
            mock_mgr.list_running_servers.return_value = [1]
            ok = await service.sync_server_states_async()
        assert ok is True
        srv1 = await uow.servers.get(1)
        srv2 = await uow.servers.get(2)
        assert srv1 is not None and srv1.status is ServerStatus.running
        assert srv2 is not None and srv2.status is ServerStatus.stopped

    async def test_with_restore_invokes_manager_then_syncs(
        self,
        service: DatabaseIntegrationService,
        uow: FakeServersUnitOfWork,
    ) -> None:
        uow.servers.seed(make_server_entity(id=1, status=ServerStatus.stopped))
        with patch(
            "app.servers.application.database_integration.minecraft_server_manager"
        ) as mock_mgr:
            mock_mgr.discover_and_restore_processes = AsyncMock(return_value={1: True})
            mock_mgr.list_running_servers.return_value = [1]
            ok = await service.sync_server_states_with_restore()
        assert ok is True
        mock_mgr.discover_and_restore_processes.assert_awaited_once()
        srv1 = await uow.servers.get(1)
        assert srv1 is not None and srv1.status is ServerStatus.running


class TestBatchAndReadHelpers:
    async def test_batch_update_returns_per_id_success(
        self,
        service: DatabaseIntegrationService,
        uow: FakeServersUnitOfWork,
    ) -> None:
        uow.servers.seed(make_server_entity(id=1, status=ServerStatus.stopped))
        uow.servers.seed(make_server_entity(id=2, status=ServerStatus.running))
        result = await service.batch_update_server_statuses_async(
            {
                1: ServerStatus.running,
                2: ServerStatus.stopped,
                99: ServerStatus.running,  # missing
            }
        )
        assert result == {1: True, 2: True, 99: False}
        srv1 = await uow.servers.get(1)
        srv2 = await uow.servers.get(2)
        assert srv1 is not None and srv1.status is ServerStatus.running
        assert srv2 is not None and srv2.status is ServerStatus.stopped

    async def test_get_servers_by_status_filters(
        self,
        service: DatabaseIntegrationService,
        uow: FakeServersUnitOfWork,
    ) -> None:
        uow.servers.seed(make_server_entity(id=1, status=ServerStatus.running))
        uow.servers.seed(make_server_entity(id=2, status=ServerStatus.running))
        uow.servers.seed(make_server_entity(id=3, status=ServerStatus.stopped))
        out = await service.get_servers_by_status_async(ServerStatus.running)
        assert sorted(s.id for s in out) == [1, 2]

    def test_is_server_running_and_listings_proxy_manager(
        self, service: DatabaseIntegrationService
    ) -> None:
        with patch(
            "app.servers.application.database_integration.minecraft_server_manager"
        ) as mock_mgr:
            mock_mgr.list_running_servers.return_value = [1, 2, 3]
            assert service.is_server_running(2) is True
            assert service.is_server_running(99) is False
            assert service.get_all_running_servers() == [1, 2, 3]

    def test_get_server_process_info_proxies_manager(
        self, service: DatabaseIntegrationService
    ) -> None:
        with patch(
            "app.servers.application.database_integration.minecraft_server_manager"
        ) as mock_mgr:
            mock_mgr.get_server_info.return_value = {"pid": 1234}
            assert service.get_server_process_info(1) == {"pid": 1234}
            mock_mgr.get_server_info.assert_called_once_with(1)


class TestModuleSingleton:
    def test_singleton_instance_exists_and_is_correct_type(self) -> None:
        assert isinstance(database_integration_service, DatabaseIntegrationService)

    def test_make_factory_returns_fresh_instance(self) -> None:
        a = make_database_integration_service()
        b = make_database_integration_service()
        assert a is not b
        assert isinstance(a, DatabaseIntegrationService)
        assert isinstance(b, DatabaseIntegrationService)
