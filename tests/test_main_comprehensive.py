"""Comprehensive tests for main application startup and lifecycle"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import (
    ServiceStatus,
    service_status,
    app
)


class TestServiceStatusComprehensive:
    """Comprehensive tests for ServiceStatus functionality"""
    
    def test_service_status_initialization(self):
        """Test ServiceStatus initializes with correct defaults"""
        status = ServiceStatus()
        
        # All services should start as not ready
        assert status.database_ready is False
        assert status.database_integration_ready is False
        assert status.backup_scheduler_ready is False
        assert status.websocket_service_ready is False
        assert status.failed_services == []

    def test_service_status_all_services_ready(self):
        """Test is_healthy when all services are ready"""
        status = ServiceStatus()
        status.database_ready = True
        status.database_integration_ready = True
        status.backup_scheduler_ready = True
        status.websocket_service_ready = True
        
        assert status.is_healthy() is True

    def test_service_status_database_not_ready(self):
        """Test is_healthy when database is not ready"""
        status = ServiceStatus()
        status.database_ready = False
        status.database_integration_ready = True
        status.backup_scheduler_ready = True
        status.websocket_service_ready = True
        
        # Database is critical - should not be healthy
        assert status.is_healthy() is False

    def test_service_status_partial_services_ready(self):
        """Test is_healthy when only some services are ready"""
        status = ServiceStatus()
        status.database_ready = True
        status.database_integration_ready = False
        status.backup_scheduler_ready = True
        status.websocket_service_ready = False
        
        # Database is ready, so should be minimally healthy
        assert status.is_healthy() is True

    def test_service_status_with_failed_services(self):
        """Test service status tracking failed services"""
        status = ServiceStatus()
        status.database_ready = True
        status.failed_services = ["backup_scheduler", "websocket_service"]
        
        # Still healthy if database is ready
        assert status.is_healthy() is True
        assert len(status.failed_services) == 2
        assert "backup_scheduler" in status.failed_services
        assert "websocket_service" in status.failed_services

    def test_get_status_complete_structure(self):
        """Test get_status returns complete status structure"""
        status = ServiceStatus()
        status.database_ready = True
        status.database_integration_ready = False
        status.backup_scheduler_ready = True
        status.websocket_service_ready = False
        status.failed_services = ["database_integration"]
        
        result = status.get_status()
        
        # Verify all expected fields
        assert "database" in result
        assert "database_integration" in result
        assert "backup_scheduler" in result
        assert "websocket_service" in result
        assert "failed_services" in result
        assert "healthy" in result
        
        # Verify values
        assert result["database"] is True
        assert result["database_integration"] is False
        assert result["backup_scheduler"] is True
        assert result["websocket_service"] is False
        assert result["failed_services"] == ["database_integration"]
        assert result["healthy"] is True

    def test_get_status_all_failed(self):
        """Test get_status when all services failed"""
        status = ServiceStatus()
        # All services remain False (default)
        status.failed_services = ["database", "database_integration", "backup_scheduler", "websocket_service"]
        
        result = status.get_status()
        
        assert result["healthy"] is False
        assert len(result["failed_services"]) == 4


class TestHealthEndpointComprehensive:
    """Comprehensive tests for health check endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    def test_health_endpoint_healthy_all_services(self, client):
        """Test health endpoint when all services are healthy"""
        with patch('app.main.service_status') as mock_status:
            mock_status.is_healthy.return_value = True
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": True,
                "backup_scheduler": True,
                "websocket_service": True,
                "failed_services": [],
                "healthy": True
            }
            
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["services"]["database"] == "operational"
            assert data["failed_services"] == []

    def test_health_endpoint_unhealthy_database(self, client):
        """Test health endpoint when database is unhealthy"""
        with patch('app.main.service_status') as mock_status:
            mock_status.is_healthy.return_value = False
            mock_status.get_status.return_value = {
                "database": False,
                "database_integration": True,
                "backup_scheduler": True,
                "websocket_service": True,
                "failed_services": ["database"],
                "healthy": False
            }
            
            response = client.get("/health")
            
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "degraded"
            assert data["services"]["database"] == "failed"
            assert "database" in data["failed_services"]

    def test_health_endpoint_partial_failures(self, client):
        """Test health endpoint with some failed services"""
        with patch('app.main.service_status') as mock_status:
            mock_status.is_healthy.return_value = True  # Database is healthy
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": False,
                "backup_scheduler": False,
                "websocket_service": True,
                "failed_services": ["database_integration", "backup_scheduler"],
                "healthy": True
            }
            
            response = client.get("/health")
            
            assert response.status_code == 200  # Still healthy due to database
            data = response.json()
            assert data["status"] == "healthy"
            assert data["services"]["database"] == "operational"
            assert len(data["failed_services"]) == 2

    def test_metrics_endpoint_basic_functionality(self, client):
        """Test metrics endpoint returns expected structure"""
        with patch('app.main.service_status') as mock_status, \
             patch('app.main.get_performance_metrics') as mock_metrics:
            
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": True,
                "backup_scheduler": True,
                "websocket_service": True,
                "failed_services": [],
                "healthy": True
            }
            mock_metrics.return_value = {
                "requests_per_second": 10.5,
                "average_response_time": 0.25
            }
            
            response = client.get("/metrics")
            
            assert response.status_code == 200
            data = response.json()
            assert "performance" in data
            assert "service_status" in data
            assert data["service_status"]["healthy"] is True

    def test_metrics_endpoint_with_service_failures(self, client):
        """Test metrics endpoint with service failures"""
        with patch('app.main.service_status') as mock_status, \
             patch('app.main.get_performance_metrics') as mock_metrics:
            
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": False,
                "backup_scheduler": True,
                "websocket_service": False,
                "failed_services": ["database_integration", "websocket_service"],
                "healthy": True
            }
            mock_metrics.return_value = {"requests_per_second": 5.0}
            
            response = client.get("/metrics")
            
            assert response.status_code == 200
            data = response.json()
            assert data["service_status"]["healthy"] is True
            assert len(data["service_status"]["failed_services"]) == 2


class TestApplicationStartupShutdown:
    """Test application startup and shutdown events"""
    
    @pytest.mark.asyncio
    async def test_lifespan_context_manager(self):
        """Test lifespan context manager functionality"""
        with patch('app.main._initialize_services') as mock_initialize, \
             patch('app.main._cleanup_services') as mock_cleanup:
            
            mock_initialize.return_value = None
            mock_cleanup.return_value = None
            
            from app.main import lifespan
            
            # Test the lifespan context manager
            async with lifespan(app):
                # During app lifetime
                pass
            
            # Verify both functions were called
            mock_initialize.assert_called_once()
            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_database_success(self):
        """Test successful database initialization"""
        with patch('app.main.Base.metadata.create_all') as mock_create_tables, \
             patch('app.main.service_status') as mock_status, \
             patch('app.main.logger') as mock_logger:
            
            from app.main import _initialize_database
            
            # Mock successful database creation
            mock_create_tables.return_value = None
            
            await _initialize_database()
            
            # Verify database tables creation
            mock_create_tables.assert_called_once()
            assert mock_status.database_ready is True
            mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_initialize_database_failure(self):
        """Test database initialization failure"""
        with patch('app.main.Base.metadata.create_all') as mock_create_tables, \
             patch('app.main.service_status') as mock_status, \
             patch('app.main.logger') as mock_logger:
            
            from app.main import _initialize_database
            
            # Mock database creation failure
            mock_create_tables.side_effect = Exception("Database connection failed")
            
            # Should raise RuntimeError for critical failure
            with pytest.raises(RuntimeError):
                await _initialize_database()
            
            # Verify error handling
            assert mock_status.database_ready is False
            assert "database" in mock_status.failed_services
            mock_logger.critical.assert_called()

    @pytest.mark.asyncio
    async def test_initialize_database_integration_success(self):
        """Test successful database integration initialization"""
        with patch('app.services.database_integration.database_integration_service') as mock_service, \
             patch('app.main.service_status') as mock_status, \
             patch('app.main.logger') as mock_logger:
            
            from app.main import _initialize_database_integration
            
            # Mock successful initialization
            mock_service.initialize.return_value = None
            mock_service.sync_server_states.return_value = None
            
            await _initialize_database_integration()
            
            # Verify initialization calls
            mock_service.initialize.assert_called_once()
            mock_service.sync_server_states.assert_called_once()
            assert mock_status.database_integration_ready is True

    @pytest.mark.asyncio
    async def test_initialize_database_integration_failure(self):
        """Test database integration initialization failure"""
        with patch('app.services.database_integration.database_integration_service') as mock_service, \
             patch('app.main.service_status') as mock_status, \
             patch('app.main.logger') as mock_logger:
            
            from app.main import _initialize_database_integration
            
            # Mock initialization failure
            mock_service.initialize.side_effect = Exception("Integration failed")
            
            # Should not raise exception (non-critical)
            await _initialize_database_integration()
            
            # Verify error handling
            assert mock_status.database_integration_ready is False
            assert "database_integration" in mock_status.failed_services
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_services_success(self):
        """Test successful service cleanup"""
        with patch('app.services.minecraft_server.minecraft_server_manager') as mock_mc_manager, \
             patch('app.services.backup_scheduler.backup_scheduler') as mock_backup_scheduler, \
             patch('app.services.websocket_service.websocket_service') as mock_ws_service, \
             patch('app.main.service_status') as mock_status, \
             patch('app.main.logger') as mock_logger:
            
            from app.main import _cleanup_services
            
            # Mock successful shutdown
            mock_mc_manager.shutdown_all = AsyncMock()
            mock_backup_scheduler.stop_scheduler = AsyncMock()
            mock_ws_service.stop_monitoring = AsyncMock()
            mock_status.backup_scheduler_ready = True
            mock_status.websocket_service_ready = True
            
            await _cleanup_services()
            
            # Verify shutdown calls
            mock_mc_manager.shutdown_all.assert_called_once()
            mock_backup_scheduler.stop_scheduler.assert_called_once()
            mock_ws_service.stop_monitoring.assert_called_once()
            mock_logger.info.assert_called_with("All services shut down cleanly")


class TestGlobalServiceStatus:
    """Test global service status instance"""
    
    def test_global_service_status_exists(self):
        """Test global service_status instance exists"""
        from app.main import service_status
        assert service_status is not None
        assert isinstance(service_status, ServiceStatus)

    def test_global_service_status_initial_state(self):
        """Test global service status has correct initial state"""
        # Create new instance to test initial state
        status = ServiceStatus()
        assert status.is_healthy() is False
        assert status.failed_services == []

    def test_global_service_status_modifications_persist(self):
        """Test modifications to global service status persist"""
        # This tests that the global instance maintains state
        original_state = service_status.database_ready
        
        # Modify state
        service_status.database_ready = not original_state
        
        # Verify change persisted
        assert service_status.database_ready == (not original_state)
        
        # Restore original state
        service_status.database_ready = original_state


class TestApplicationConfiguration:
    """Test application configuration and setup"""
    
    def test_app_instance_exists(self):
        """Test FastAPI app instance exists"""
        from app.main import app
        assert app is not None
        assert hasattr(app, 'router')

    def test_app_has_required_routes(self):
        """Test app has required health and metrics routes"""
        from app.main import app
        
        # Get all route paths
        routes = [route.path for route in app.routes]
        
        # Check required endpoints exist
        assert "/health" in routes
        assert "/metrics" in routes

    def test_app_includes_routers(self):
        """Test app includes all required routers"""
        from app.main import app
        
        # Get all routes to verify routers are included
        routes = [route.path for route in app.routes]
        
        # Check that various router endpoints exist
        auth_routes = [route for route in routes if route.startswith("/api/v1/auth")]
        user_routes = [route for route in routes if route.startswith("/api/v1/users")]
        server_routes = [route for route in routes if route.startswith("/api/v1/servers")]
        backup_routes = [route for route in routes if "/backups" in route]
        
        assert len(auth_routes) > 0, "Auth routes not found"
        assert len(user_routes) > 0, "User routes not found"  
        assert len(server_routes) > 0, "Server routes not found"
        assert len(backup_routes) > 0, "Backup routes not found"

    def test_app_middleware_configuration(self):
        """Test app middleware is properly configured"""
        from app.main import app
        
        # Verify middleware is configured
        assert hasattr(app, 'user_middleware')
        assert len(app.user_middleware) > 0
        
        # Check for specific middleware types
        middleware_names = [str(mw) for mw in app.user_middleware]
        # Should have CORS, Audit, and Performance middleware
        assert len(middleware_names) >= 3


class TestServiceIntegrationBasic:
    """Basic integration tests for service imports"""
    
    def test_service_imports_work(self):
        """Test that all services can be imported without errors"""
        # Test database integration service import
        from app.services.database_integration import database_integration_service
        assert database_integration_service is not None
        
        # Test websocket service import  
        from app.services.websocket_service import websocket_service
        assert websocket_service is not None
        
        # Test backup scheduler import
        from app.services.backup_scheduler import backup_scheduler
        assert backup_scheduler is not None
        
        # Test minecraft server manager import
        from app.services.minecraft_server import minecraft_server_manager
        assert minecraft_server_manager is not None

    def test_service_instances_have_required_methods(self):
        """Test that service instances have required methods"""
        from app.services.database_integration import database_integration_service
        from app.services.websocket_service import websocket_service
        from app.services.backup_scheduler import backup_scheduler
        
        # Database integration service methods
        assert hasattr(database_integration_service, 'initialize')
        assert hasattr(database_integration_service, 'sync_server_states')
        
        # WebSocket service methods
        assert hasattr(websocket_service, 'start_monitoring')
        assert hasattr(websocket_service, 'stop_monitoring')
        
        # Backup scheduler methods
        assert hasattr(backup_scheduler, 'start_scheduler')
        assert hasattr(backup_scheduler, 'stop_scheduler')