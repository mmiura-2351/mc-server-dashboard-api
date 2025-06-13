"""Comprehensive tests for app/main.py startup and health check logic"""
import json
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import (
    ServiceStatus,
    app,
    service_status,
    _initialize_services,
    _initialize_database,
    _initialize_database_integration,
    _initialize_backup_scheduler,
    _initialize_websocket_service,
    _cleanup_services,
)


class TestServiceStatus:
    """Test ServiceStatus class functionality"""
    
    def test_init(self):
        """Test ServiceStatus initialization"""
        status = ServiceStatus()
        
        assert status.database_ready is False
        assert status.database_integration_ready is False
        assert status.backup_scheduler_ready is False
        assert status.websocket_service_ready is False
        assert status.failed_services == []
    
    def test_is_healthy_database_ready(self):
        """Test is_healthy returns True when database is ready"""
        status = ServiceStatus()
        status.database_ready = True
        
        assert status.is_healthy() is True
    
    def test_is_healthy_database_not_ready(self):
        """Test is_healthy returns False when database is not ready"""
        status = ServiceStatus()
        status.database_ready = False
        
        assert status.is_healthy() is False
    
    def test_get_status_all_services_ready(self):
        """Test get_status when all services are ready"""
        status = ServiceStatus()
        status.database_ready = True
        status.database_integration_ready = True
        status.backup_scheduler_ready = True
        status.websocket_service_ready = True
        
        result = status.get_status()
        
        assert result["database"] is True
        assert result["database_integration"] is True
        assert result["backup_scheduler"] is True
        assert result["websocket_service"] is True
        assert result["failed_services"] == []
        assert result["healthy"] is True
    
    def test_get_status_with_failures(self):
        """Test get_status with failed services"""
        status = ServiceStatus()
        status.database_ready = True
        status.failed_services = ["websocket_service", "backup_scheduler"]
        
        result = status.get_status()
        
        assert result["database"] is True
        assert result["database_integration"] is False
        assert result["backup_scheduler"] is False
        assert result["websocket_service"] is False
        assert result["failed_services"] == ["websocket_service", "backup_scheduler"]
        assert result["healthy"] is True  # Database is ready


class TestDatabaseInitialization:
    """Test database initialization logic"""
    
    @pytest.mark.asyncio
    async def test_initialize_database_success(self):
        """Test successful database initialization"""
        global service_status
        service_status = ServiceStatus()
        
        with patch('app.main.Base') as mock_base, \
             patch('app.main.engine') as mock_engine:
            
            await _initialize_database()
            
            mock_base.metadata.create_all.assert_called_once_with(bind=mock_engine)
            assert service_status.database_ready is True
            assert "database" not in service_status.failed_services
    
    @pytest.mark.asyncio
    async def test_initialize_database_failure(self):
        """Test database initialization failure"""
        global service_status
        service_status = ServiceStatus()
        
        with patch('app.main.Base') as mock_base, \
             patch('app.main.engine'):
            
            mock_base.metadata.create_all.side_effect = Exception("Database connection failed")
            
            with pytest.raises(RuntimeError, match="Critical database initialization failed"):
                await _initialize_database()
            
            assert service_status.database_ready is False
            assert "database" in service_status.failed_services


class TestDatabaseIntegrationInitialization:
    """Test database integration initialization"""
    
    @pytest.mark.asyncio
    async def test_initialize_database_integration_success(self):
        """Test successful database integration initialization"""
        global service_status
        service_status = ServiceStatus()
        
        mock_service = Mock()
        mock_service.initialize = Mock()
        mock_service.sync_server_states = Mock()
        
        with patch('app.main.database_integration_service', mock_service):
            await _initialize_database_integration()
            
            mock_service.initialize.assert_called_once()
            mock_service.sync_server_states.assert_called_once()
            assert service_status.database_integration_ready is True
            assert "database_integration" not in service_status.failed_services
    
    @pytest.mark.asyncio
    async def test_initialize_database_integration_sync_failure(self):
        """Test database integration with sync failure (should continue)"""
        global service_status
        service_status = ServiceStatus()
        
        mock_service = Mock()
        mock_service.initialize = Mock()
        mock_service.sync_server_states.side_effect = Exception("Sync failed")
        
        with patch('app.main.database_integration_service', mock_service):
            await _initialize_database_integration()
            
            mock_service.initialize.assert_called_once()
            mock_service.sync_server_states.assert_called_once()
            assert service_status.database_integration_ready is True
            assert "database_integration" not in service_status.failed_services
    
    @pytest.mark.asyncio
    async def test_initialize_database_integration_init_failure(self):
        """Test database integration initialization failure"""
        global service_status
        service_status = ServiceStatus()
        
        with patch('app.main.database_integration_service') as mock_service:
            mock_service.initialize.side_effect = Exception("Init failed")
            
            await _initialize_database_integration()
            
            assert service_status.database_integration_ready is False
            assert "database_integration" in service_status.failed_services


class TestBackupSchedulerInitialization:
    """Test backup scheduler initialization"""
    
    @pytest.mark.asyncio
    async def test_initialize_backup_scheduler_success(self):
        """Test successful backup scheduler initialization"""
        global service_status
        service_status = ServiceStatus()
        
        mock_scheduler = AsyncMock()
        mock_scheduler.start_scheduler = AsyncMock()
        
        with patch('app.main.backup_scheduler', mock_scheduler):
            await _initialize_backup_scheduler()
            
            mock_scheduler.start_scheduler.assert_called_once()
            assert service_status.backup_scheduler_ready is True
            assert "backup_scheduler" not in service_status.failed_services
    
    @pytest.mark.asyncio
    async def test_initialize_backup_scheduler_failure(self):
        """Test backup scheduler initialization failure"""
        global service_status
        service_status = ServiceStatus()
        
        with patch('app.main.backup_scheduler') as mock_scheduler:
            mock_scheduler.start_scheduler.side_effect = Exception("Scheduler failed")
            
            await _initialize_backup_scheduler()
            
            assert service_status.backup_scheduler_ready is False
            assert "backup_scheduler" in service_status.failed_services


class TestWebSocketServiceInitialization:
    """Test WebSocket service initialization"""
    
    @pytest.mark.asyncio
    async def test_initialize_websocket_service_success(self):
        """Test successful WebSocket service initialization"""
        global service_status
        service_status = ServiceStatus()
        
        mock_service = AsyncMock()
        mock_service.start_monitoring = AsyncMock()
        
        with patch('app.main.websocket_service', mock_service):
            await _initialize_websocket_service()
            
            mock_service.start_monitoring.assert_called_once()
            assert service_status.websocket_service_ready is True
            assert "websocket_service" not in service_status.failed_services
    
    @pytest.mark.asyncio
    async def test_initialize_websocket_service_failure(self):
        """Test WebSocket service initialization failure"""
        global service_status
        service_status = ServiceStatus()
        
        with patch('app.main.websocket_service') as mock_service:
            mock_service.start_monitoring.side_effect = Exception("WebSocket failed")
            
            await _initialize_websocket_service()
            
            assert service_status.websocket_service_ready is False
            assert "websocket_service" in service_status.failed_services


class TestServiceInitialization:
    """Test complete service initialization"""
    
    @pytest.mark.asyncio
    async def test_initialize_services_all_success(self):
        """Test successful initialization of all services"""
        global service_status
        service_status = ServiceStatus()
        
        with patch('app.main._initialize_database') as mock_db, \
             patch('app.main._initialize_database_integration') as mock_db_int, \
             patch('app.main._initialize_backup_scheduler') as mock_backup, \
             patch('app.main._initialize_websocket_service') as mock_ws:
            
            mock_db.return_value = AsyncMock()
            mock_db_int.return_value = AsyncMock()
            mock_backup.return_value = AsyncMock()
            mock_ws.return_value = AsyncMock()
            
            await _initialize_services()
            
            mock_db.assert_called_once()
            mock_db_int.assert_called_once()
            mock_backup.assert_called_once()
            mock_ws.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_initialize_services_database_failure_stops_startup(self):
        """Test that database failure stops startup"""
        global service_status
        service_status = ServiceStatus()
        
        with patch('app.main._initialize_database') as mock_db, \
             patch('app.main._initialize_database_integration') as mock_db_int:
            
            mock_db.side_effect = RuntimeError("Database failed")
            
            with pytest.raises(RuntimeError, match="Database failed"):
                await _initialize_services()
            
            mock_db.assert_called_once()
            mock_db_int.assert_not_called()  # Should not continue after database failure


class TestCleanupServices:
    """Test service cleanup during shutdown"""
    
    @pytest.mark.asyncio
    async def test_cleanup_services_all_ready(self):
        """Test cleanup when all services are ready"""
        global service_status
        service_status = ServiceStatus()
        service_status.backup_scheduler_ready = True
        service_status.websocket_service_ready = True
        
        mock_server_manager = AsyncMock()
        mock_server_manager.shutdown_all = AsyncMock()
        
        mock_backup_scheduler = AsyncMock()
        mock_backup_scheduler.stop_scheduler = AsyncMock()
        
        mock_websocket_service = AsyncMock()
        mock_websocket_service.stop_monitoring = AsyncMock()
        
        with patch('app.main.minecraft_server_manager', mock_server_manager), \
             patch('app.main.backup_scheduler', mock_backup_scheduler), \
             patch('app.main.websocket_service', mock_websocket_service):
            
            await _cleanup_services()
            
            mock_server_manager.shutdown_all.assert_called_once()
            mock_backup_scheduler.stop_scheduler.assert_called_once()
            mock_websocket_service.stop_monitoring.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_services_with_errors(self):
        """Test cleanup continues even with errors"""
        global service_status
        service_status = ServiceStatus()
        service_status.backup_scheduler_ready = True
        service_status.websocket_service_ready = True
        
        mock_server_manager = AsyncMock()
        mock_server_manager.shutdown_all.side_effect = Exception("Server shutdown failed")
        
        mock_backup_scheduler = AsyncMock()
        mock_backup_scheduler.stop_scheduler.side_effect = Exception("Backup stop failed")
        
        mock_websocket_service = AsyncMock()
        mock_websocket_service.stop_monitoring = AsyncMock()
        
        with patch('app.main.minecraft_server_manager', mock_server_manager), \
             patch('app.main.backup_scheduler', mock_backup_scheduler), \
             patch('app.main.websocket_service', mock_websocket_service):
            
            await _cleanup_services()
            
            # All should be called despite errors
            mock_server_manager.shutdown_all.assert_called_once()
            mock_backup_scheduler.stop_scheduler.assert_called_once()
            mock_websocket_service.stop_monitoring.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_services_not_ready(self):
        """Test cleanup when services are not ready"""
        global service_status
        service_status = ServiceStatus()
        service_status.backup_scheduler_ready = False
        service_status.websocket_service_ready = False
        
        mock_server_manager = AsyncMock()
        mock_server_manager.shutdown_all = AsyncMock()
        
        with patch('app.main.minecraft_server_manager', mock_server_manager):
            await _cleanup_services()
            
            mock_server_manager.shutdown_all.assert_called_once()
            # Backup and WebSocket should not be called


class TestHealthCheckEndpoint:
    """Test health check endpoint"""
    
    def test_health_check_healthy_status(self):
        """Test health check when all services are healthy"""
        global service_status
        service_status = ServiceStatus()
        service_status.database_ready = True
        service_status.database_integration_ready = True
        service_status.backup_scheduler_ready = True
        service_status.websocket_service_ready = True
        
        client = TestClient(app)
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["database"] == "operational"
        assert data["services"]["database_integration"] == "operational"
        assert data["services"]["backup_scheduler"] == "operational"
        assert data["services"]["websocket_service"] == "operational"
        assert data["failed_services"] == []
        assert "All services operational" in data["message"]
        assert "timestamp" in data
    
    def test_health_check_degraded_status(self):
        """Test health check when some services have failed"""
        global service_status
        service_status = ServiceStatus()
        service_status.database_ready = True
        service_status.database_integration_ready = False
        service_status.backup_scheduler_ready = False
        service_status.websocket_service_ready = False
        service_status.failed_services = ["database_integration", "backup_scheduler"]
        
        client = TestClient(app)
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"  # Database is ready
        assert data["services"]["database"] == "operational"
        assert data["services"]["database_integration"] == "failed"
        assert data["services"]["backup_scheduler"] == "failed"
        assert data["services"]["websocket_service"] == "failed"
        assert "database_integration" in data["failed_services"]
        assert "backup_scheduler" in data["failed_services"]
    
    def test_health_check_unhealthy_status(self):
        """Test health check when database is not ready"""
        global service_status
        service_status = ServiceStatus()
        service_status.database_ready = False
        service_status.failed_services = ["database"]
        
        client = TestClient(app)
        response = client.get("/health")
        
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["database"] == "failed"
        assert "database" in data["failed_services"]
        assert "Running with degraded functionality" in data["message"]


class TestMetricsEndpoint:
    """Test metrics endpoint"""
    
    def test_get_metrics(self):
        """Test metrics endpoint returns performance data"""
        global service_status
        service_status = ServiceStatus()
        service_status.database_ready = True
        
        mock_metrics = {
            "request_count": 100,
            "avg_response_time": 0.5,
            "active_connections": 5
        }
        
        with patch('app.main.get_performance_metrics', return_value=mock_metrics):
            client = TestClient(app)
            response = client.get("/metrics")
            
            assert response.status_code == 200
            data = response.json()
            assert data["performance"] == mock_metrics
            assert "service_status" in data
            assert "timestamp" in data
            assert data["message"] == "Performance metrics collected successfully"