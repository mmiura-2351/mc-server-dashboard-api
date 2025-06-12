"""Tests for DatabaseIntegrationService with transaction management"""
from unittest.mock import Mock, patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.core.database_utils import RetryExhaustedException, TransactionException
from app.servers.models import Server, ServerStatus
from app.services.database_integration import database_integration_service


class TestDatabaseIntegrationService:
    """Test DatabaseIntegrationService methods"""
    
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
        """Create service instance with mocked SessionLocal"""
        service = database_integration_service
        service.SessionLocal = Mock()
        return service
    
    def test_update_server_status_success(self, service, mock_session):
        """Test successful server status update"""
        service.SessionLocal.return_value = mock_session
        
        # Mock server query
        mock_server = Mock(spec=Server)
        mock_server.id = 1
        mock_server.status = ServerStatus.stopped
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.first.return_value = mock_server
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx:
            mock_with_tx.return_value = True
            
            result = service.update_server_status(1, ServerStatus.running)
            
            assert result is True
            mock_with_tx.assert_called_once()
    
    def test_update_server_status_not_found(self, service, mock_session):
        """Test update when server not found"""
        service.SessionLocal.return_value = mock_session
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.first.return_value = None
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx:
            mock_with_tx.return_value = False
            
            result = service.update_server_status(999, ServerStatus.running)
            
            assert result is False
    
    def test_update_server_status_retry_exhausted(self, service, mock_session):
        """Test update when retries are exhausted"""
        service.SessionLocal.return_value = mock_session
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx:
            mock_with_tx.side_effect = RetryExhaustedException("All retries failed")
            
            result = service.update_server_status(1, ServerStatus.running)
            
            assert result is False
    
    def test_sync_server_states_success(self, service, mock_session):
        """Test successful server state synchronization"""
        service.SessionLocal.return_value = mock_session
        
        # Mock servers in database
        mock_servers = [
            Mock(id=1, status=ServerStatus.stopped, is_deleted=False),
            Mock(id=2, status=ServerStatus.running, is_deleted=False),
            Mock(id=3, status=ServerStatus.running, is_deleted=False),
        ]
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = mock_servers
        
        # Mock running servers from manager
        with patch('app.services.database_integration.minecraft_server_manager') as mock_manager:
            mock_manager.list_running_servers.return_value = [1, 2]  # Server 3 is not running
            
            with patch('app.services.database_integration.with_transaction') as mock_with_tx:
                # Mock with_transaction to actually call the function so state changes happen
                def call_function(session, func, *args, **kwargs):
                    return func(session)
                mock_with_tx.side_effect = call_function
                
                result = service.sync_server_states()
                
                assert result is True
                # Server 1 should be updated to running
                assert mock_servers[0].status == ServerStatus.running
                # Server 2 should remain running
                assert mock_servers[1].status == ServerStatus.running
                # Server 3 should be updated to stopped
                assert mock_servers[2].status == ServerStatus.stopped
    
    def test_sync_server_states_no_servers(self, service, mock_session):
        """Test sync when no servers exist"""
        service.SessionLocal.return_value = mock_session
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = []
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx:
            mock_with_tx.return_value = True
            
            result = service.sync_server_states()
            
            assert result is True
    
    def test_batch_update_server_statuses(self, service, mock_session):
        """Test batch update of server statuses"""
        service.SessionLocal.return_value = mock_session
        
        # Mock servers
        mock_servers = [
            Mock(id=1, status=ServerStatus.stopped),
            Mock(id=2, status=ServerStatus.running),
        ]
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = mock_servers
        
        status_updates = {
            1: ServerStatus.running,
            2: ServerStatus.stopped,
            3: ServerStatus.running,  # This server doesn't exist
        }
        
        with patch('app.services.database_integration.with_transaction') as mock_with_tx:
            # Mock with_transaction to actually call the function so state changes happen
            def call_function(session, func, *args, **kwargs):
                return func(session)
            mock_with_tx.side_effect = call_function
            
            result = service.batch_update_server_statuses(status_updates)
            
            assert result[1] is True
            assert result[2] is True
            assert result[3] is False
            assert mock_servers[0].status == ServerStatus.running
            assert mock_servers[1].status == ServerStatus.stopped
    
    def test_get_servers_by_status(self, service, mock_session):
        """Test getting servers by status"""
        service.SessionLocal.return_value = mock_session
        
        mock_servers = [
            Mock(id=1, status=ServerStatus.running),
            Mock(id=2, status=ServerStatus.running),
        ]
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = mock_servers
        mock_session.expunge = Mock()
        
        result = service.get_servers_by_status(ServerStatus.running)
        
        assert len(result) == 2
        assert result == mock_servers
        # Verify that expunge was called for each server
        assert mock_session.expunge.call_count == 2
    
    def test_get_servers_by_status_error(self, service, mock_session):
        """Test error handling in get_servers_by_status"""
        service.SessionLocal.return_value = mock_session
        
        mock_session.query.side_effect = Exception("Database error")
        
        result = service.get_servers_by_status(ServerStatus.running)
        
        assert result == []