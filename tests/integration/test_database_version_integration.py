"""
Integration tests for database-based version management in server creation.

Tests that server creation now uses fast database queries instead of slow external API calls.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import FileOperationException
from app.servers.models import ServerType
from app.servers.schemas import ServerCreateRequest
from app.servers.service import ServerJarService, ServerService
from app.users.models import Role, User
from app.versions.models import MinecraftVersion


class TestDatabaseVersionIntegration:
    """Integration tests for database-based version management"""

    @pytest.fixture
    def server_service(self):
        return ServerService()

    @pytest.fixture
    def jar_service(self):
        return ServerJarService()

    @pytest.fixture
    def mock_admin_user(self):
        user = User(
            id=1,
            username="admin",
            email="admin@test.com",
            is_active=True,
            is_approved=True,
            role=Role.admin
        )
        return user

    @pytest.fixture
    def sample_create_request(self):
        return ServerCreateRequest(
            name="test-server",
            description="Test server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
            max_memory=1024,
            max_players=20,
            port=25565
        )

    @pytest.fixture
    def sample_db_version(self, db: Session):
        """Create a sample version in database"""

        # Create version directly using SQLAlchemy model
        db_version = MinecraftVersion(
            server_type="vanilla",  # Use string value for enum
            version="1.21.6",
            download_url="https://launcher.mojang.com/v1/objects/test.jar",
            is_stable=True,
            is_active=True
        )

        db.add(db_version)
        db.commit()
        return db_version

    @pytest.mark.asyncio
    async def test_server_creation_uses_database_validation(
        self, server_service, sample_create_request, mock_admin_user, db, sample_db_version
    ):
        """Test that server creation uses database for version validation (FAST)"""

        # Mock filesystem operations to avoid actual file creation
        with patch.object(server_service.filesystem_service, 'create_server_directory') as mock_create_dir, \
             patch.object(server_service.jar_service, 'get_server_jar') as mock_get_jar, \
             patch.object(server_service.filesystem_service, 'generate_server_files') as mock_gen_files, \
             patch.object(server_service, '_validate_java_compatibility') as mock_java_compat:

            # Setup mocks
            mock_create_dir.return_value = "/tmp/test-server"
            mock_get_jar.return_value = "/tmp/test-server/server.jar"
            mock_gen_files.return_value = None
            mock_java_compat.return_value = None

            # Create server - this should use database validation
            result = await server_service.create_server(sample_create_request, mock_admin_user, db)

            # Verify result
            assert result.name == "test-server"
            assert result.minecraft_version == "1.21.6"
            assert result.server_type == ServerType.vanilla

            # Verify jar service was called with database session
            mock_get_jar.assert_called_once()
            args = mock_get_jar.call_args[0]
            assert args[0] == ServerType.vanilla  # server_type
            assert args[1] == "1.21.6"  # minecraft_version
            # args[2] is server_dir, args[3] should be db session
            assert len(mock_get_jar.call_args[0]) == 4  # Includes db parameter

    @pytest.mark.asyncio
    async def test_jar_service_database_validation_fast_path(
        self, jar_service, db, sample_db_version
    ):
        """Test that JAR service uses database for version validation (FAST PATH)"""

        # Mock external dependencies
        with patch.object(jar_service.cache_manager, 'get_or_download_jar') as mock_cache, \
             patch.object(jar_service.cache_manager, 'copy_jar_to_server') as mock_copy:

            mock_cache.return_value = "/cache/vanilla-1.21.6.jar"
            mock_copy.return_value = "/server/server.jar"

            # Call get_server_jar - should use database validation
            result = await jar_service.get_server_jar(
                ServerType.vanilla, "1.21.6", "/tmp/test-server", db
            )

            # Verify result
            assert result == "/server/server.jar"

            # Verify cache was called with correct download URL from database
            mock_cache.assert_called_once_with(
                ServerType.vanilla,
                "1.21.6",
                "https://launcher.mojang.com/v1/objects/test.jar"
            )

    @pytest.mark.asyncio
    async def test_jar_service_error_on_unsupported_version(
        self, jar_service, db
    ):
        """Test that JAR service raises error when version not supported"""

        # Call with version not in database - should raise error instead of fallback
        with pytest.raises(FileOperationException, match="Version 1.20.0 is not supported"):
            await jar_service.get_server_jar(
                ServerType.vanilla, "1.20.0", "/tmp/test-server", db
            )

    @pytest.mark.asyncio
    async def test_server_service_database_validation_unsupported_version(
        self, server_service, mock_admin_user, db
    ):
        """Test that server creation rejects unsupported versions from database"""

        # Create request with unsupported version
        request = ServerCreateRequest(
            name="test-server",
            description="Test server",
            minecraft_version="1.99.99",  # This version doesn't exist in database
            server_type=ServerType.vanilla,
            max_memory=1024,
            max_players=20,
            port=25565
        )

        # Mock filesystem and validation to avoid unrelated errors
        # Also mock jar service to ensure version validation happens first
        with patch.object(server_service.validation_service, 'validate_server_uniqueness') as mock_unique, \
             patch.object(server_service, '_validate_java_compatibility') as mock_java, \
             patch.object(server_service.filesystem_service, 'create_server_directory') as mock_dir, \
             patch.object(server_service.jar_service, '_is_version_supported_db') as mock_jar_version_check:

            mock_unique.return_value = None
            mock_java.return_value = None
            mock_dir.return_value = Path("/tmp/test-server")
            # Make jar service version check return False (unsupported)
            mock_jar_version_check.return_value = False

            # Should raise FileOperationException wrapping the version validation error
            with pytest.raises(FileOperationException) as exc_info:
                await server_service.create_server(request, mock_admin_user, db)

            # Verify error message mentions unsupported version
            assert "not supported" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_database_only_performance(
        self, jar_service, db, sample_db_version
    ):
        """Test that database-only approach provides fast performance"""
        import time

        # Test database path timing
        with patch.object(jar_service.cache_manager, 'get_or_download_jar') as mock_cache, \
             patch.object(jar_service.cache_manager, 'copy_jar_to_server') as mock_copy:

            mock_cache.return_value = "/cache/test.jar"
            mock_copy.return_value = "/server/server.jar"

            # Measure database path
            start_time = time.time()
            await jar_service.get_server_jar(
                ServerType.vanilla, "1.21.6", "/tmp/test", db
            )
            db_time = time.time() - start_time

            # Database path should be very fast (< 50ms typically)
            assert db_time < 0.1  # 100ms threshold for CI environments
            print(f"Database performance: {db_time*1000:.1f}ms")

        # Test that unsupported versions fail fast
        start_time = time.time()
        try:
            await jar_service.get_server_jar(
                ServerType.vanilla, "1.19.0", "/tmp/test", db  # Version not in DB
            )
        except FileOperationException:
            pass  # Expected error
        error_time = time.time() - start_time

        # Error should also be fast
        assert error_time < 0.1  # 100ms threshold for CI environments
        print(f"Error handling performance: {error_time*1000:.1f}ms")
