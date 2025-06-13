"""Enhanced tests for DatabaseIntegrationService covering missing paths"""
from unittest.mock import Mock, patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.core.database_utils import RetryExhaustedException, TransactionException
from app.servers.models import Server, ServerStatus
from app.services.database_integration import (
    DatabaseIntegrationService, 
    database_integration_service
)


class TestDatabaseIntegrationServiceEnhanced:
    """Enhanced tests for DatabaseIntegrationService covering missing paths"""
    
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
    
    @pytest.fixture
    def service(self):
        """Create fresh service instance with mocked SessionLocal"""
        service = DatabaseIntegrationService()
        service.SessionLocal = Mock()
        return service


class TestServiceInitialization(TestDatabaseIntegrationServiceEnhanced):
    """Test service initialization and callbacks"""
    
    def test_init_creates_sessionlocal(self, service):
        """Test __init__ sets SessionLocal properly"""
        # Test that the service uses the main SessionLocal
        from app.core.database import SessionLocal
        
        new_service = DatabaseIntegrationService()
        assert new_service.SessionLocal is SessionLocal
    
    @patch('app.services.database_integration.minecraft_server_manager')
    def test_initialize_sets_callback(self, mock_manager, service):
        """Test initialize sets status update callback"""
        service.initialize()
        
        mock_manager.set_status_update_callback.assert_called_once_with(
            service.update_server_status
        )
    
    @patch('app.services.database_integration.minecraft_server_manager')
    def test_initialize_logging(self, mock_manager, service):
        """Test initialize logs initialization"""
        with patch('app.services.database_integration.logger') as mock_logger:
            service.initialize()
            
            mock_logger.info.assert_called_with("Database integration initialized")


class TestUpdateServerStatusErrorPaths(TestDatabaseIntegrationServiceEnhanced):
    """Test error paths in update_server_status"""
    
    def test_update_server_status_transaction_exception(self, service, mock_session):
        """Test update_server_status handles TransactionException"""
        service.SessionLocal.return_value = mock_session
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx:
            mock_with_tx.side_effect = TransactionException("Integrity error")
            
            result = service.update_server_status(1, ServerStatus.running)
            
            assert result is False
    
    def test_update_server_status_general_exception(self, service, mock_session):
        """Test update_server_status handles general exceptions"""
        service.SessionLocal.return_value = mock_session
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx:
            mock_with_tx.side_effect = ValueError("Unexpected error")
            
            result = service.update_server_status(1, ServerStatus.running)
            
            assert result is False
    
    def test_update_server_status_logging_on_retry_exhausted(self, service, mock_session):
        """Test logging when retry is exhausted"""
        service.SessionLocal.return_value = mock_session
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            mock_with_tx.side_effect = RetryExhaustedException("All retries failed")
            
            result = service.update_server_status(1, ServerStatus.running)
            
            assert result is False
            mock_logger.error.assert_called_with(
                "Failed to update server 1 status after all retry attempts"
            )
    
    def test_update_server_status_logging_on_transaction_error(self, service, mock_session):
        """Test logging on transaction error"""
        service.SessionLocal.return_value = mock_session
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            mock_with_tx.side_effect = TransactionException("Integrity error")
            
            result = service.update_server_status(1, ServerStatus.running)
            
            assert result is False
            mock_logger.error.assert_called_with(
                "Transaction error updating server 1 status: Integrity error"
            )
    
    def test_update_server_status_logging_on_unexpected_error(self, service, mock_session):
        """Test logging on unexpected error with exc_info"""
        service.SessionLocal.return_value = mock_session
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            mock_with_tx.side_effect = ValueError("Unexpected error")
            
            result = service.update_server_status(1, ServerStatus.running)
            
            assert result is False
            mock_logger.error.assert_called_with(
                "Unexpected error updating server 1 status: Unexpected error",
                exc_info=True
            )


class TestSyncServerStatesErrorPaths(TestDatabaseIntegrationServiceEnhanced):
    """Test error paths in sync_server_states"""
    
    def test_sync_server_states_retry_exhausted(self, service, mock_session):
        """Test sync_server_states handles retry exhausted"""
        service.SessionLocal.return_value = mock_session
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            mock_with_tx.side_effect = RetryExhaustedException("All retries failed")
            
            result = service.sync_server_states()
            
            assert result is False
            mock_logger.error.assert_called_with(
                "Failed to sync server states after all retry attempts"
            )
    
    def test_sync_server_states_transaction_exception(self, service, mock_session):
        """Test sync_server_states handles transaction exception"""
        service.SessionLocal.return_value = mock_session
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            mock_with_tx.side_effect = TransactionException("Transaction failed")
            
            result = service.sync_server_states()
            
            assert result is False
            mock_logger.error.assert_called_with(
                "Transaction error syncing server states: Transaction failed"
            )
    
    def test_sync_server_states_general_exception(self, service, mock_session):
        """Test sync_server_states handles general exception"""
        service.SessionLocal.return_value = mock_session
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            mock_with_tx.side_effect = RuntimeError("Unexpected error")
            
            result = service.sync_server_states()
            
            assert result is False
            mock_logger.error.assert_called_with(
                "Unexpected error syncing server states: Unexpected error",
                exc_info=True
            )


class TestHelperMethods(TestDatabaseIntegrationServiceEnhanced):
    """Test helper methods"""
    
    @patch('app.services.database_integration.minecraft_server_manager')
    def test_get_server_process_info(self, mock_manager, service):
        """Test get_server_process_info delegates to manager"""
        mock_info = {"pid": 1234, "memory": "512MB"}
        mock_manager.get_server_info.return_value = mock_info
        
        result = service.get_server_process_info(1)
        
        assert result == mock_info
        mock_manager.get_server_info.assert_called_once_with(1)
    
    @patch('app.services.database_integration.minecraft_server_manager')
    def test_is_server_running_true(self, mock_manager, service):
        """Test is_server_running returns True when server is running"""
        mock_manager.list_running_servers.return_value = [1, 2, 3]
        
        result = service.is_server_running(1)
        
        assert result is True
    
    @patch('app.services.database_integration.minecraft_server_manager')
    def test_is_server_running_false(self, mock_manager, service):
        """Test is_server_running returns False when server is not running"""
        mock_manager.list_running_servers.return_value = [2, 3, 4]
        
        result = service.is_server_running(1)
        
        assert result is False
    
    @patch('app.services.database_integration.minecraft_server_manager')
    def test_get_all_running_servers(self, mock_manager, service):
        """Test get_all_running_servers delegates to manager"""
        mock_servers = [1, 2, 3, 4]
        mock_manager.list_running_servers.return_value = mock_servers
        
        result = service.get_all_running_servers()
        
        assert result == mock_servers
        mock_manager.list_running_servers.assert_called_once()


class TestBatchUpdateErrorPaths(TestDatabaseIntegrationServiceEnhanced):
    """Test error paths in batch_update_server_statuses"""
    
    def test_batch_update_retry_exhausted(self, service, mock_session):
        """Test batch_update handles retry exhausted"""
        service.SessionLocal.return_value = mock_session
        
        status_updates = {1: ServerStatus.running, 2: ServerStatus.stopped}
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            mock_with_tx.side_effect = RetryExhaustedException("All retries failed")
            
            result = service.batch_update_server_statuses(status_updates)
            
            assert result == {1: False, 2: False}
            mock_logger.error.assert_called_with(
                "Failed to batch update server statuses after all retry attempts"
            )
    
    def test_batch_update_transaction_exception(self, service, mock_session):
        """Test batch_update handles transaction exception"""
        service.SessionLocal.return_value = mock_session
        
        status_updates = {1: ServerStatus.running}
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            mock_with_tx.side_effect = TransactionException("Transaction failed")
            
            result = service.batch_update_server_statuses(status_updates)
            
            assert result == {1: False}
            mock_logger.error.assert_called_with(
                "Transaction error in batch update: Transaction failed"
            )
    
    def test_batch_update_general_exception(self, service, mock_session):
        """Test batch_update handles general exception"""
        service.SessionLocal.return_value = mock_session
        
        status_updates = {1: ServerStatus.running}
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            mock_with_tx.side_effect = RuntimeError("Unexpected error")
            
            result = service.batch_update_server_statuses(status_updates)
            
            assert result == {1: False}
            mock_logger.error.assert_called_with(
                "Unexpected error in batch update: Unexpected error",
                exc_info=True
            )


class TestSyncServerStatesLogic(TestDatabaseIntegrationServiceEnhanced):
    """Test detailed sync_server_states logic"""
    
    def test_sync_server_states_no_updates_needed(self, service, mock_session):
        """Test sync when no updates are needed"""
        service.SessionLocal.return_value = mock_session
        
        # Mock servers that are already in sync
        mock_servers = [
            Mock(id=1, status=ServerStatus.running, is_deleted=False),
            Mock(id=2, status=ServerStatus.stopped, is_deleted=False),
        ]
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = mock_servers
        
        with patch('app.services.database_integration.minecraft_server_manager') as mock_manager, \
             patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            # Server 1 is running, server 2 is stopped - both match DB
            mock_manager.list_running_servers.return_value = [1]
            
            def call_function(session, func, *args, **kwargs):
                return func(session)
            mock_with_tx.side_effect = call_function
            
            result = service.sync_server_states()
            
            assert result is True
            # No status changes should occur
            assert mock_servers[0].status == ServerStatus.running
            assert mock_servers[1].status == ServerStatus.stopped
            
            # Should log completion
            mock_logger.info.assert_any_call("Server state synchronization completed")
    
    def test_sync_server_states_with_corrections_needed(self, service, mock_session):
        """Test sync when corrections are needed"""
        service.SessionLocal.return_value = mock_session
        
        # Mock servers with status mismatches
        mock_servers = [
            Mock(id=1, status=ServerStatus.stopped, is_deleted=False),  # Should be running
            Mock(id=2, status=ServerStatus.running, is_deleted=False),  # Should be stopped
            Mock(id=3, status=ServerStatus.starting, is_deleted=False), # Should be stopped
            Mock(id=4, status=ServerStatus.error, is_deleted=False),    # Should be running
        ]
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = mock_servers
        
        with patch('app.services.database_integration.minecraft_server_manager') as mock_manager, \
             patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            # Only servers 1 and 4 are actually running
            mock_manager.list_running_servers.return_value = [1, 4]
            
            def call_function(session, func, *args, **kwargs):
                return func(session)
            mock_with_tx.side_effect = call_function
            
            result = service.sync_server_states()
            
            assert result is True
            
            # Server 1: stopped -> running
            assert mock_servers[0].status == ServerStatus.running
            # Server 2: running -> stopped  
            assert mock_servers[1].status == ServerStatus.stopped
            # Server 3: starting -> stopped
            assert mock_servers[2].status == ServerStatus.stopped
            # Server 4: error -> running
            assert mock_servers[3].status == ServerStatus.running
            
            # Should log updates
            mock_logger.info.assert_any_call("Updating 4 server statuses")
    
    def test_sync_server_states_empty_database(self, service, mock_session):
        """Test sync when no servers exist in database"""
        service.SessionLocal.return_value = mock_session
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = []
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx, \
             patch('app.services.database_integration.logger') as mock_logger:
            
            def call_function(session, func, *args, **kwargs):
                return func(session)
            mock_with_tx.side_effect = call_function
            
            result = service.sync_server_states()
            
            assert result is True
            mock_logger.info.assert_any_call("No servers to synchronize")


class TestGlobalServiceInstance:
    """Test the global service instance"""
    
    def test_global_service_exists(self):
        """Test global database_integration_service exists"""
        assert database_integration_service is not None
        assert isinstance(database_integration_service, DatabaseIntegrationService)
    
    def test_global_service_has_correct_sessionlocal(self):
        """Test global service uses correct SessionLocal"""
        from app.core.database import SessionLocal
        
        assert database_integration_service.SessionLocal is SessionLocal