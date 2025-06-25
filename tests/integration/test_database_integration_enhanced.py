"""Enhanced tests for database integration service with actual functionality testing"""

from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from app.core.database_utils import RetryExhaustedException, TransactionException
from app.servers.models import Server, ServerStatus
from app.services.database_integration import (
    DatabaseIntegrationService,
    database_integration_service,
)


class TestDatabaseIntegrationServiceEnhanced:
    """Enhanced tests for database integration service functionality"""

    @pytest.fixture
    def service(self):
        """Create service instance with mocked SessionLocal"""
        service = DatabaseIntegrationService()
        service.SessionLocal = Mock()
        return service

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session"""
        session = Mock(spec=Session)
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=None)
        session.query = Mock()
        session.commit = Mock()
        session.rollback = Mock()
        return session

    def test_service_initialization_functionality(self, service):
        """Test service initialization with actual functionality"""
        # Test SessionLocal is properly set
        from app.core.database import SessionLocal

        real_service = DatabaseIntegrationService()
        assert real_service.SessionLocal is SessionLocal

        # Test initialization sets callback
        with patch(
            "app.services.database_integration.minecraft_server_manager"
        ) as mock_mgr:
            real_service.initialize()
            mock_mgr.set_status_update_callback.assert_called_once_with(
                real_service.update_server_status
            )

    def test_update_server_status_complete_workflow(self, service, mock_session):
        """Test complete server status update workflow"""
        service.SessionLocal.return_value = mock_session

        # Setup server query chain
        mock_server = Mock(spec=Server)
        mock_server.id = 1
        mock_server.status = ServerStatus.stopped

        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.first.return_value = mock_server

        with patch("app.services.database_integration.with_transaction") as mock_with_tx:
            # Mock transaction to actually execute the update function
            # with_transaction(session, func, *args, max_retries=X, backoff_factor=Y)
            # The func should receive (session, *args) but not the retry params
            def execute_update(session, update_func, *args, **kwargs):
                # Extract only the function args, not the retry configuration
                return update_func(session, *args)

            mock_with_tx.side_effect = execute_update

            result = service.update_server_status(1, ServerStatus.running)

            # Verify the update was applied
            assert result is True
            assert mock_server.status == ServerStatus.running
            mock_with_tx.assert_called_once()

    def test_update_server_status_with_logging(self, service, mock_session):
        """Test server status update includes proper logging"""
        service.SessionLocal.return_value = mock_session

        mock_server = Mock(spec=Server)
        mock_server.id = 1
        mock_server.status = ServerStatus.stopped

        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.first.return_value = mock_server

        with (
            patch("app.services.database_integration.with_transaction") as mock_with_tx,
            patch("app.services.database_integration.logger") as mock_logger,
        ):

            def execute_update(session, update_func, *args, **kwargs):
                return update_func(session, *args)

            mock_with_tx.side_effect = execute_update

            result = service.update_server_status(1, ServerStatus.running)

            # Verify logging occurred
            assert result is True
            mock_logger.info.assert_called_with(
                "Updated server 1 status: ServerStatus.stopped -> ServerStatus.running"
            )

    def test_sync_server_states_comprehensive(self, service, mock_session):
        """Test comprehensive server state synchronization"""
        service.SessionLocal.return_value = mock_session

        # Create servers with various state mismatches
        mock_servers = [
            Mock(
                id=1, status=ServerStatus.stopped, is_deleted=False
            ),  # Should be running
            Mock(
                id=2, status=ServerStatus.running, is_deleted=False
            ),  # Should be stopped
            Mock(
                id=3, status=ServerStatus.starting, is_deleted=False
            ),  # Should be stopped
            Mock(id=4, status=ServerStatus.error, is_deleted=False),  # Should be running
            Mock(id=5, status=ServerStatus.running, is_deleted=False),  # Already correct
        ]

        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = mock_servers

        with (
            patch(
                "app.services.database_integration.minecraft_server_manager"
            ) as mock_manager,
            patch("app.services.database_integration.with_transaction") as mock_with_tx,
            patch("app.services.database_integration.logger") as mock_logger,
        ):
            # Only servers 1, 4, and 5 are actually running
            mock_manager.list_running_servers.return_value = [1, 4, 5]

            def execute_sync(session, sync_func, *args, **kwargs):
                return sync_func(session)

            mock_with_tx.side_effect = execute_sync

            result = service.sync_server_states()

            # Verify state corrections
            assert result is True
            assert mock_servers[0].status == ServerStatus.running  # 1: stopped -> running
            assert mock_servers[1].status == ServerStatus.stopped  # 2: running -> stopped
            assert (
                mock_servers[2].status == ServerStatus.stopped
            )  # 3: starting -> stopped
            assert mock_servers[3].status == ServerStatus.running  # 4: error -> running
            assert mock_servers[4].status == ServerStatus.running  # 5: unchanged

            # Verify logging of updates
            mock_logger.info.assert_any_call("Updating 4 server statuses")

    def test_sync_server_states_with_no_updates_needed(self, service, mock_session):
        """Test sync when all servers are already in correct state"""
        service.SessionLocal.return_value = mock_session

        mock_servers = [
            Mock(id=1, status=ServerStatus.running, is_deleted=False),
            Mock(id=2, status=ServerStatus.stopped, is_deleted=False),
        ]

        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = mock_servers

        with (
            patch(
                "app.services.database_integration.minecraft_server_manager"
            ) as mock_manager,
            patch("app.services.database_integration.with_transaction") as mock_with_tx,
            patch("app.services.database_integration.logger") as mock_logger,
        ):
            # States match: server 1 running, server 2 stopped
            mock_manager.list_running_servers.return_value = [1]

            def execute_sync(session, sync_func, *args, **kwargs):
                return sync_func(session)

            mock_with_tx.side_effect = execute_sync

            result = service.sync_server_states()

            # No status changes should occur
            assert result is True
            assert mock_servers[0].status == ServerStatus.running
            assert mock_servers[1].status == ServerStatus.stopped

            # Should log completion but no updates
            mock_logger.info.assert_any_call("Server state synchronization completed")

    def test_batch_update_server_statuses_functionality(self, service, mock_session):
        """Test batch update functionality with real logic"""
        service.SessionLocal.return_value = mock_session

        # Mock existing servers
        mock_servers = [
            Mock(id=1, status=ServerStatus.stopped),
            Mock(id=2, status=ServerStatus.running),
            Mock(id=3, status=ServerStatus.error),
        ]

        # Create server mapping for query results
        server_map = {1: mock_servers[0], 2: mock_servers[1], 3: mock_servers[2]}

        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = mock_servers

        status_updates = {
            1: ServerStatus.running,
            2: ServerStatus.stopped,
            3: ServerStatus.running,
            4: ServerStatus.running,  # Non-existent server
        }

        with (
            patch("app.services.database_integration.with_transaction") as mock_with_tx,
            patch("app.services.database_integration.logger") as mock_logger,
        ):

            def execute_batch_update(session, update_func, *args, **kwargs):
                return update_func(session)

            mock_with_tx.side_effect = execute_batch_update

            result = service.batch_update_server_statuses(status_updates)

            # Verify results
            assert result[1] is True  # Updated successfully
            assert result[2] is True  # Updated successfully
            assert result[3] is True  # Updated successfully
            assert result[4] is False  # Server not found

            # Verify actual status changes
            assert mock_servers[0].status == ServerStatus.running
            assert mock_servers[1].status == ServerStatus.stopped
            assert mock_servers[2].status == ServerStatus.running

            # Verify logging of batch updates
            mock_logger.info.assert_any_call(
                "Batch update: Server 1 status: ServerStatus.stopped -> ServerStatus.running"
            )

    def test_get_servers_by_status_functionality(self, service, mock_session):
        """Test getting servers by status with session management"""
        service.SessionLocal.return_value = mock_session

        # Mock servers with specific status
        running_servers = [
            Mock(id=1, status=ServerStatus.running),
            Mock(id=3, status=ServerStatus.running),
        ]

        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = running_servers

        result = service.get_servers_by_status(ServerStatus.running)

        # Verify query construction
        assert result == running_servers
        mock_session.query.assert_called_once_with(Server)

        # Verify session.expunge was called for each server
        assert mock_session.expunge.call_count == 2
        for server in running_servers:
            mock_session.expunge.assert_any_call(server)

    def test_minecraft_server_manager_integration(self, service):
        """Test integration with minecraft server manager"""
        with patch(
            "app.services.database_integration.minecraft_server_manager"
        ) as mock_manager:
            # Test get_server_process_info
            mock_info = {"pid": 1234, "cpu_usage": 15.5, "memory_mb": 512}
            mock_manager.get_server_info.return_value = mock_info

            result = service.get_server_process_info(1)
            assert result == mock_info
            mock_manager.get_server_info.assert_called_once_with(1)

            # Test is_server_running
            mock_manager.list_running_servers.return_value = [1, 2, 3]

            assert service.is_server_running(1) is True
            assert service.is_server_running(4) is False

            # Test get_all_running_servers
            result = service.get_all_running_servers()
            assert result == [1, 2, 3]

    def test_error_handling_with_proper_cleanup(self, service, mock_session):
        """Test error handling ensures proper cleanup"""
        service.SessionLocal.return_value = mock_session

        with patch("app.services.database_integration.with_transaction") as mock_with_tx:
            # Test RetryExhaustedException
            mock_with_tx.side_effect = RetryExhaustedException("Retries exhausted")

            result = service.update_server_status(1, ServerStatus.running)
            assert result is False

            # Test TransactionException
            mock_with_tx.side_effect = TransactionException("Transaction failed")

            result = service.sync_server_states()
            assert result is False

            # Test general exception
            mock_with_tx.side_effect = RuntimeError("Unexpected error")

            result = service.batch_update_server_statuses({1: ServerStatus.running})
            assert result == {1: False}

    def test_global_service_instance_functionality(self):
        """Test the global service instance has correct configuration"""
        # Verify global instance exists and is configured
        assert database_integration_service is not None
        assert isinstance(database_integration_service, DatabaseIntegrationService)

        # Verify it uses the correct SessionLocal
        from app.core.database import SessionLocal

        assert database_integration_service.SessionLocal is SessionLocal

        # Test that initialize method exists and is callable
        assert hasattr(database_integration_service, "initialize")
        assert callable(database_integration_service.initialize)

    def test_service_callback_integration(self, service):
        """Test service callback integration with minecraft server manager"""
        with patch(
            "app.services.database_integration.minecraft_server_manager"
        ) as mock_manager:
            # Initialize service to set callback
            service.initialize()

            # Verify callback was registered
            mock_manager.set_status_update_callback.assert_called_once_with(
                service.update_server_status
            )

            # Test the callback is the actual method
            callback_arg = mock_manager.set_status_update_callback.call_args[0][0]
            assert callback_arg == service.update_server_status

    def test_database_transaction_configuration(self, service, mock_session):
        """Test database transaction configuration and retry logic"""
        service.SessionLocal.return_value = mock_session

        # Setup server query chain for update_server_status
        mock_server = Mock(spec=Server)
        mock_server.id = 1
        mock_server.status = ServerStatus.stopped

        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.first.return_value = mock_server

        with (
            patch("app.services.database_integration.with_transaction") as mock_with_tx,
            patch("app.services.database_integration.settings") as mock_settings,
        ):
            # Setup settings
            mock_settings.DATABASE_MAX_RETRIES = 3
            mock_settings.DATABASE_RETRY_BACKOFF = 0.1

            # Mock with_transaction to execute the function and return True
            def execute_with_config(session, update_func, *args, **kwargs):
                return update_func(session, *args)

            mock_with_tx.side_effect = execute_with_config

            result = service.update_server_status(1, ServerStatus.running)

            # Verify transaction was called with correct settings
            assert result is True
            mock_with_tx.assert_called_once()
            call_kwargs = mock_with_tx.call_args.kwargs
            assert call_kwargs["max_retries"] == 3
            assert call_kwargs["backoff_factor"] == 0.1
