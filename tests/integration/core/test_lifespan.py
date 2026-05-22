"""Comprehensive tests for main application startup and lifecycle"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import ServiceStatus, app, service_status


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
        assert status.version_update_scheduler_ready is False
        assert status.failed_services == []

    def test_service_status_all_services_ready(self):
        """Test is_healthy when all services are ready"""
        status = ServiceStatus()
        status.database_ready = True
        status.database_integration_ready = True
        status.backup_scheduler_ready = True
        status.websocket_service_ready = True
        status.version_update_scheduler_ready = True

        assert status.is_healthy() is True

    def test_service_status_database_not_ready(self):
        """Test is_healthy when database is not ready"""
        status = ServiceStatus()
        status.database_ready = False
        status.database_integration_ready = True
        status.backup_scheduler_ready = True
        status.websocket_service_ready = True
        status.version_update_scheduler_ready = True

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
        status.failed_services = [
            "database",
            "database_integration",
            "backup_scheduler",
            "websocket_service",
        ]

        result = status.get_status()

        assert result["healthy"] is False
        assert len(result["failed_services"]) == 4


class TestHealthEndpointComprehensive:
    """Comprehensive tests for health check endpoints"""

    # `client` fixture provided by tests/conftest.py (Issue #168).

    def test_health_endpoint_healthy_all_services(self, client):
        """Test health endpoint when all services are healthy"""
        with patch("app.main.service_status") as mock_status:
            mock_status.is_healthy.return_value = True
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": True,
                "backup_scheduler": True,
                "websocket_service": True,
                "version_update_scheduler": True,
                "failed_services": [],
                "healthy": True,
            }

            response = client.get("/api/v1/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["services"]["database"] == "operational"
            assert data["failed_services"] == []

    def test_health_endpoint_unhealthy_database(self, client):
        """Test health endpoint when database is unhealthy.

        Post-#21: the legacy wire format is preserved, but the
        underlying evaluation goes through ``HealthCheckService``. We
        therefore override the service rather than poking
        ``service_status``.
        """
        from tests.integration.core._health_helpers import (
            override_health_service,
            unhealthy_database_components,
        )

        with override_health_service(unhealthy_database_components()):
            response = client.get("/api/v1/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["database"] == "failed"
        assert "database" in data["failed_services"]

    def test_health_endpoint_partial_failures(self, client):
        """Test health endpoint with some failed services (#21 wire compat)."""
        from tests.integration.core._health_helpers import (
            override_health_service,
            partial_failure_components,
        )

        with override_health_service(partial_failure_components()):
            response = client.get("/api/v1/health")

        assert response.status_code == 200  # Still healthy due to database
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["database"] == "operational"
        assert len(data["failed_services"]) == 2

    def test_metrics_endpoint_basic_functionality(self, client):
        """Test metrics endpoint returns expected structure"""
        with (
            patch("app.main.service_status") as mock_status,
            patch("app.main.get_performance_metrics") as mock_metrics,
        ):
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": True,
                "backup_scheduler": True,
                "websocket_service": True,
                "version_update_scheduler": True,
                "failed_services": [],
                "healthy": True,
            }
            mock_metrics.return_value = {
                "requests_per_second": 10.5,
                "average_response_time": 0.25,
            }

            response = client.get("/api/v1/metrics")

            assert response.status_code == 200
            data = response.json()
            assert "performance" in data
            assert "service_status" in data
            assert data["service_status"]["healthy"] is True

    def test_metrics_endpoint_with_service_failures(self, client):
        """Test metrics endpoint with service failures"""
        with (
            patch("app.main.service_status") as mock_status,
            patch("app.main.get_performance_metrics") as mock_metrics,
        ):
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": False,
                "backup_scheduler": True,
                "websocket_service": False,
                "version_update_scheduler": True,
                "failed_services": ["database_integration", "websocket_service"],
                "healthy": True,
            }
            mock_metrics.return_value = {"requests_per_second": 5.0}

            response = client.get("/api/v1/metrics")

            assert response.status_code == 200
            data = response.json()
            assert data["service_status"]["healthy"] is True
            assert len(data["service_status"]["failed_services"]) == 2


class TestApplicationStartupShutdown:
    """Test application startup and shutdown events"""

    @pytest.mark.asyncio
    async def test_lifespan_context_manager(self):
        """Test lifespan context manager functionality"""
        with (
            patch("app.main._initialize_services") as mock_initialize,
            patch("app.main._cleanup_services") as mock_cleanup,
        ):
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
        with (
            patch("app.main.Base.metadata.create_all") as mock_create_tables,
            patch("app.main.service_status") as mock_status,
            patch("app.main.logger") as mock_logger,
        ):
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
        with (
            patch("app.main.Base.metadata.create_all") as mock_create_tables,
            patch("app.main.service_status") as mock_status,
            patch("app.main.logger") as mock_logger,
        ):
            from app.main import _initialize_database

            # Setup mock service status
            mock_status.database_ready = False
            mock_status.failed_services = []

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
    async def test_initialize_visibility_migration_success(self):
        """Backfill invokes the migration service and logs the result.

        Verifies the lifespan hook constructs the service through the
        documented factory, calls `migrate_all_resources`, and closes
        the session it opened. Idempotency itself is exercised by the
        domain-level tests in
        ``tests/unit/core/visibility/test_service_with_fake.py``.
        """
        mock_service = AsyncMock()
        mock_service.migrate_all_resources = AsyncMock(
            return_value={"servers": 2, "groups": 1, "total": 3}
        )
        mock_db = MagicMock()

        with (
            patch("app.core.database.SessionLocal", return_value=mock_db),
            patch(
                "app.core.visibility.api.dependencies.make_visibility_migration_service",
                return_value=mock_service,
            ) as mock_factory,
            patch("app.main.logger") as mock_logger,
        ):
            from app.main import _initialize_visibility_migration

            await _initialize_visibility_migration()

            mock_factory.assert_called_once_with(mock_db)
            mock_service.migrate_all_resources.assert_awaited_once()
            mock_db.close.assert_called_once()
            mock_logger.info.assert_called()
            # Best-effort hook must not signal failure
            mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_visibility_migration_failure_swallowed(self):
        """Migration failure logs a warning and lets startup continue.

        Best-effort backfill: the lifespan must never abort because of a
        migration error; operators re-trigger via the admin endpoint.
        """
        mock_service = AsyncMock()
        mock_service.migrate_all_resources = AsyncMock(side_effect=RuntimeError("boom"))
        mock_db = MagicMock()

        with (
            patch("app.core.database.SessionLocal", return_value=mock_db),
            patch(
                "app.core.visibility.api.dependencies.make_visibility_migration_service",
                return_value=mock_service,
            ),
            patch("app.main.service_status") as mock_status,
            patch("app.main.logger") as mock_logger,
        ):
            mock_status.failed_services = []
            from app.main import _initialize_visibility_migration

            # Must not raise
            await _initialize_visibility_migration()

            mock_logger.warning.assert_called()
            # Session must still be closed even when migration raises
            mock_db.close.assert_called_once()
            # Best-effort hook does not flag the system as degraded
            assert "visibility_migration" not in mock_status.failed_services

    @pytest.mark.asyncio
    async def test_initialize_visibility_migration_slow_warning(self):
        """Slow backfill (>=1s) emits a warning breadcrumb for operators."""
        import asyncio

        mock_db = MagicMock()

        async def slow_migrate():
            # Yield control so the wall-clock can advance under the
            # patched ``time.monotonic`` below.
            await asyncio.sleep(0)
            return {"servers": 0, "groups": 0, "total": 0}

        mock_service = AsyncMock()
        mock_service.migrate_all_resources = AsyncMock(side_effect=slow_migrate)

        # Fake a >=1s elapsed window via deterministic monotonic clock
        clock = iter([0.0, 1.5])
        with (
            patch("app.core.database.SessionLocal", return_value=mock_db),
            patch(
                "app.core.visibility.api.dependencies.make_visibility_migration_service",
                return_value=mock_service,
            ),
            patch("time.monotonic", side_effect=lambda: next(clock)),
            patch("app.main.logger") as mock_logger,
        ):
            from app.main import _initialize_visibility_migration

            await _initialize_visibility_migration()

            mock_logger.warning.assert_called()
            mock_db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_database_integration_success(self):
        """Test successful database integration initialization.

        The lifespan now builds a fresh service via
        ``make_database_integration_service()`` and publishes it on the
        ``database_integration_instance`` holder (PR #279 B1). We
        assert the holder ends up with the freshly built mock, which is
        what downstream callers (shim, routers) resolve through.
        """
        from app.servers.application.database_integration import (
            database_integration_instance,
        )

        mock_service = AsyncMock()
        mock_service.initialize = MagicMock(return_value=None)
        previous = (
            database_integration_instance.get()
            if database_integration_instance.is_set()
            else None
        )
        database_integration_instance.clear()
        try:
            with (
                patch(
                    "app.servers.application.database_integration.make_database_integration_service",
                    return_value=mock_service,
                ),
                patch("app.main.service_status") as mock_status,
                patch("app.main.logger"),
            ):
                from app.main import _initialize_database_integration

                await _initialize_database_integration()

                # Verify initialization calls
                mock_service.initialize.assert_called_once()
                mock_service.sync_server_states_with_restore.assert_awaited_once()
                assert mock_status.database_integration_ready is True
                # Holder must hold the freshly built mock — this is what
                # ``app.servers.application.database_integration`` resolves through.
                assert database_integration_instance.get() is mock_service
        finally:
            if previous is None:
                database_integration_instance.clear()
            else:
                database_integration_instance.set(previous)

    @pytest.mark.asyncio
    async def test_initialize_database_integration_failure(self):
        """Test database integration initialization failure.

        The lifespan must leave the holder empty so a follow-up
        ``database_integration_service`` lookup raises the clear
        "not initialised" RuntimeError (PR #279 B1 holder-clear path).
        """
        from app.servers.application.database_integration import (
            database_integration_instance,
        )

        mock_service = MagicMock()
        mock_service.initialize.side_effect = Exception("Integration failed")
        previous = (
            database_integration_instance.get()
            if database_integration_instance.is_set()
            else None
        )
        database_integration_instance.clear()
        try:
            with (
                patch(
                    "app.servers.application.database_integration.make_database_integration_service",
                    return_value=mock_service,
                ),
                patch("app.main.service_status") as mock_status,
                patch("app.main.logger") as mock_logger,
            ):
                from app.main import _initialize_database_integration

                # Setup mock service status
                mock_status.database_integration_ready = False
                mock_status.failed_services = []

                # Should not raise exception (non-critical)
                await _initialize_database_integration()

                # Verify error handling
                assert mock_status.database_integration_ready is False
                assert "database_integration" in mock_status.failed_services
                mock_logger.error.assert_called()
                # Holder must remain empty so downstream lookups raise
                # explicit RuntimeError rather than returning a
                # half-initialised service.
                assert not database_integration_instance.is_set()
        finally:
            if previous is not None:
                database_integration_instance.set(previous)

    @pytest.mark.asyncio
    async def test_cleanup_services_success(self):
        """Test successful service cleanup"""
        # `backup_scheduler` is now resolved through the lifespan-scoped
        # `backup_scheduler_instance` holder (#227); patch the holder
        # so `_cleanup_services` sees a mock instance.
        mock_scheduler = AsyncMock()
        mock_scheduler.stop_scheduler = AsyncMock()

        with (
            patch(
                "app.servers.application.minecraft_server.minecraft_server_manager"
            ) as mock_mc_manager,
            patch("app.backups.backup_scheduler_instance") as mock_holder,
            patch(
                "app.websockets.application.service.websocket_service"
            ) as mock_ws_service,
            patch("app.main.service_status") as mock_status,
            patch("app.main.logger") as mock_logger,
        ):
            from app.main import _cleanup_services

            mock_holder.get.return_value = mock_scheduler
            mock_holder.clear = lambda: None
            mock_mc_manager.shutdown_all = AsyncMock()
            mock_ws_service.stop_monitoring = AsyncMock()
            mock_status.backup_scheduler_ready = True
            mock_status.websocket_service_ready = True

            await _cleanup_services()

            mock_mc_manager.shutdown_all.assert_called_once()
            mock_scheduler.stop_scheduler.assert_called_once()
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
        assert hasattr(app, "router")

    def test_app_has_required_routes(self):
        """Test app has required health and metrics routes"""
        from app.main import app

        # Get all route paths
        routes = [route.path for route in app.routes]

        # Check required endpoints exist
        assert "/api/v1/health" in routes
        assert "/api/v1/metrics" in routes

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
        assert hasattr(app, "user_middleware")
        assert len(app.user_middleware) > 0

        # Check for specific middleware types
        middleware_names = [str(mw) for mw in app.user_middleware]
        # Should have CORS, Audit, and Performance middleware
        assert len(middleware_names) >= 3


class TestApiV1EndpointsNew:
    """Test new /api/v1 prefixed health and metrics endpoints (TDD approach)"""

    # `client` fixture provided by tests/conftest.py (Issue #168).

    def test_api_v1_health_endpoint_healthy_all_services(self, client):
        """Test /api/v1/health endpoint when all services are healthy"""
        with patch("app.main.service_status") as mock_status:
            mock_status.is_healthy.return_value = True
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": True,
                "backup_scheduler": True,
                "websocket_service": True,
                "version_update_scheduler": True,
                "failed_services": [],
                "healthy": True,
            }

            response = client.get("/api/v1/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["services"]["database"] == "operational"
            assert data["failed_services"] == []

    def test_api_v1_health_endpoint_unhealthy_database(self, client):
        """Test /api/v1/health endpoint when database is unhealthy (#21 wire compat)."""
        from tests.integration.core._health_helpers import (
            override_health_service,
            unhealthy_database_components,
        )

        with override_health_service(unhealthy_database_components()):
            response = client.get("/api/v1/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["database"] == "failed"
        assert "database" in data["failed_services"]

    def test_api_v1_metrics_endpoint_basic_functionality(self, client):
        """Test /api/v1/metrics endpoint returns expected structure"""
        with (
            patch("app.main.service_status") as mock_status,
            patch("app.main.get_performance_metrics") as mock_metrics,
        ):
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": True,
                "backup_scheduler": True,
                "websocket_service": True,
                "version_update_scheduler": True,
                "failed_services": [],
                "healthy": True,
            }
            mock_metrics.return_value = {
                "requests_per_second": 10.5,
                "average_response_time": 0.25,
            }

            response = client.get("/api/v1/metrics")

            assert response.status_code == 200
            data = response.json()
            assert "performance" in data
            assert "service_status" in data
            assert data["service_status"]["healthy"] is True

    def test_api_v1_metrics_endpoint_with_service_failures(self, client):
        """Test /api/v1/metrics endpoint with service failures"""
        with (
            patch("app.main.service_status") as mock_status,
            patch("app.main.get_performance_metrics") as mock_metrics,
        ):
            mock_status.get_status.return_value = {
                "database": True,
                "database_integration": False,
                "backup_scheduler": True,
                "websocket_service": False,
                "version_update_scheduler": True,
                "failed_services": ["database_integration", "websocket_service"],
                "healthy": True,
            }
            mock_metrics.return_value = {"requests_per_second": 5.0}

            response = client.get("/api/v1/metrics")

            assert response.status_code == 200
            data = response.json()
            assert data["service_status"]["healthy"] is True
            assert len(data["service_status"]["failed_services"]) == 2


class TestServiceIntegrationBasic:
    """Basic integration tests for service imports"""

    def test_service_imports_work(self):
        """Test that all services can be imported without errors.

        The ``database_integration`` shim now resolves the service
        lazily through ``database_integration_instance`` (PR #279 B1
        holder pattern), so the import-only assertion targets the
        factory + holder rather than the (lifespan-only) singleton.
        """
        # Test database integration service factory + holder import
        from app.servers.application.database_integration import (
            database_integration_instance,
            make_database_integration_service,
        )

        assert database_integration_instance is not None
        assert make_database_integration_service is not None

        # Test websocket service import
        from app.websockets.application.service import websocket_service

        assert websocket_service is not None

        # Test backup scheduler import
        from app.backups.application.scheduler import backup_scheduler

        assert backup_scheduler is not None

        # Test minecraft server manager import
        from app.servers.application.minecraft_server import minecraft_server_manager

        assert minecraft_server_manager is not None

    def test_service_instances_have_required_methods(self):
        """Test that service instances have required methods.

        For ``database_integration_service`` we inspect the class
        directly because the module-level name is now resolved through
        the holder (PR #279 B1) and only exists after lifespan startup.
        """
        from app.backups.application.scheduler import backup_scheduler
        from app.servers.application.database_integration import (
            DatabaseIntegrationService,
        )
        from app.websockets.application.service import websocket_service

        # Database integration service methods
        assert hasattr(DatabaseIntegrationService, "initialize")
        assert hasattr(DatabaseIntegrationService, "sync_server_states")

        # WebSocket service methods
        assert hasattr(websocket_service, "start_monitoring")
        assert hasattr(websocket_service, "stop_monitoring")

        # Backup scheduler methods
        assert hasattr(backup_scheduler, "start_scheduler")
        assert hasattr(backup_scheduler, "stop_scheduler")
