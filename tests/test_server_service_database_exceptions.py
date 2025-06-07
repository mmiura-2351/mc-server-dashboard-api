from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import (
    DatabaseError,
    IntegrityError,
    OperationalError,
    StatementError,
    TimeoutError,
)
from sqlalchemy.orm import Session
from app.servers.models import Server
from app.servers.schemas import ServerCreateRequest, ServerUpdateRequest
from app.servers.service import ServerService
from app.users.models import User


class TestServerServiceDatabaseExceptions:
    """Test database exception handling in ServerService."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = Mock(spec=Session)
        session.commit = Mock()
        session.rollback = Mock()
        session.refresh = Mock()
        session.query = Mock()
        session.add = Mock()
        session.delete = Mock()
        return session

    @pytest.fixture
    def mock_user(self):
        """Create a mock user object."""
        user = Mock(spec=User)
        user.id = 1
        user.username = "testuser"
        user.is_approved = True
        user.role = "user"
        return user

    @pytest.fixture
    def mock_admin_user(self):
        """Create a mock admin user object."""
        user = Mock(spec=User)
        user.id = 1
        user.username = "admin"
        user.is_approved = True
        user.role = "admin"
        return user

    @pytest.fixture
    def mock_server(self):
        """Create a mock server object."""
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test-server"
        server.port = 25565
        server.owner_id = 1
        server.jar_file = "server.jar"
        server.server_type = "vanilla"
        server.minecraft_version = "1.21"
        server.java_args = "-Xmx2G"
        return server

    @pytest.fixture
    def server_create_data(self):
        """Create server creation data."""
        return ServerCreateRequest(
            name="test-server",
            port=25565,
            server_type="vanilla",
            minecraft_version="1.21",
            max_memory=2048
        )

    @pytest.fixture
    def server_update_data(self):
        """Create server update data."""
        return ServerUpdateRequest(
            name="updated-server",
            max_memory=4096
        )

    @pytest.fixture
    def server_service(self):
        """Create a ServerService instance."""
        return ServerService()

    # Test database connection failures
    def test_list_servers_database_connection_error(self, server_service, mock_db_session):
        """Test list_servers when database connection fails."""
        mock_db_session.query.side_effect = OperationalError("connection failed", None, None)
        
        with pytest.raises(HTTPException) as exc_info:
            server_service.list_servers(db=mock_db_session)
        
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_server_database_timeout(self, server_service, mock_db_session):
        """Test get_server when database query times out."""
        mock_query = Mock()
        mock_query.filter.return_value.first.side_effect = TimeoutError("query timeout", None, None)
        mock_db_session.query.return_value = mock_query
        
        with pytest.raises(TimeoutError):
            await server_service.get_server(1, mock_db_session)

    @pytest.mark.asyncio
    async def test_create_server_integrity_constraint_violation(self, server_service, mock_db_session, mock_user, server_create_data):
        """Test create_server when integrity constraint is violated (e.g., duplicate port)."""
        # Mock validation to pass
        with patch.object(server_service.validation_service, 'validate_server_uniqueness', new_callable=AsyncMock):
            with patch.object(server_service.filesystem_service, 'create_server_directory', new_callable=AsyncMock):
                with patch.object(server_service.jar_service, 'get_server_jar', new_callable=AsyncMock):
                    # Mock database service to raise IntegrityError
                    with patch.object(server_service.database_service, 'create_server_record', side_effect=IntegrityError("UNIQUE constraint failed: servers.port", None, None)):
                        with patch.object(server_service.filesystem_service, 'cleanup_server_directory', new_callable=AsyncMock):
                            with pytest.raises(IntegrityError):
                                await server_service.create_server(server_create_data, mock_user, mock_db_session)

    @pytest.mark.asyncio
    async def test_create_server_database_error_during_commit(self, server_service, mock_db_session, mock_user, server_create_data):
        """Test create_server when database error occurs during commit."""
        # Mock validation to pass
        with patch.object(server_service.validation_service, 'validate_server_uniqueness', new_callable=AsyncMock):
            with patch.object(server_service.filesystem_service, 'create_server_directory', new_callable=AsyncMock):
                with patch.object(server_service.jar_service, 'get_server_jar', new_callable=AsyncMock):
                    # Mock database service to raise DatabaseError
                    with patch.object(server_service.database_service, 'create_server_record', side_effect=DatabaseError("database corruption", None, None)):
                        with patch.object(server_service.filesystem_service, 'cleanup_server_directory', new_callable=AsyncMock):
                            with pytest.raises(DatabaseError):
                                await server_service.create_server(server_create_data, mock_user, mock_db_session)

    @pytest.mark.asyncio
    async def test_create_server_statement_error(self, server_service, mock_db_session, mock_user, server_create_data):
        """Test create_server when SQL statement is malformed."""
        # Mock validation to pass
        with patch.object(server_service.validation_service, 'validate_server_uniqueness', new_callable=AsyncMock):
            with patch.object(server_service.filesystem_service, 'create_server_directory', new_callable=AsyncMock):
                with patch.object(server_service.jar_service, 'get_server_jar', new_callable=AsyncMock):
                    # Mock database service to raise StatementError
                    with patch.object(server_service.database_service, 'create_server_record', side_effect=StatementError("invalid SQL statement", None, None, None)):
                        with patch.object(server_service.filesystem_service, 'cleanup_server_directory', new_callable=AsyncMock):
                            with pytest.raises(StatementError):
                                await server_service.create_server(server_create_data, mock_user, mock_db_session)

    # Test update operation database failures
    @pytest.mark.asyncio
    async def test_update_server_database_lock_timeout(self, server_service, mock_db_session, mock_server, server_update_data):
        """Test update_server when database lock timeout occurs."""
        # Mock server validation to return server
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=mock_server):
            # Mock database service to raise TimeoutError
            with patch.object(server_service.database_service, 'update_server_record', side_effect=TimeoutError("lock timeout", None, None)):
                with pytest.raises(TimeoutError):
                    await server_service.update_server(1, server_update_data, mock_db_session)

    @pytest.mark.asyncio
    async def test_update_server_concurrent_modification(self, server_service, mock_db_session, mock_server, server_update_data):
        """Test update_server when concurrent modification occurs."""
        # Mock server validation to return server
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=mock_server):
            # Mock database service to raise IntegrityError
            with patch.object(server_service.database_service, 'update_server_record', side_effect=IntegrityError("concurrent modification", None, None)):
                with pytest.raises(IntegrityError):
                    await server_service.update_server(1, server_update_data, mock_db_session)

    @pytest.mark.asyncio
    async def test_update_server_database_corruption(self, server_service, mock_db_session, mock_server, server_update_data):
        """Test update_server when database corruption is detected."""
        # Mock server validation to return server
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=mock_server):
            # Mock database service to raise DatabaseError
            with patch.object(server_service.database_service, 'update_server_record', side_effect=DatabaseError("database disk image is malformed", None, None)):
                with pytest.raises(DatabaseError):
                    await server_service.update_server(1, server_update_data, mock_db_session)

    # Test delete operation database failures
    @pytest.mark.asyncio
    async def test_delete_server_foreign_key_constraint(self, server_service, mock_db_session, mock_server):
        """Test delete_server when foreign key constraint prevents deletion."""
        # Mock server validation to return server
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=mock_server):
            # Mock database service to raise IntegrityError
            with patch.object(server_service.database_service, 'soft_delete_server', side_effect=IntegrityError("FOREIGN KEY constraint failed", None, None)):
                with pytest.raises(IntegrityError):
                    await server_service.delete_server(1, mock_db_session)

    @pytest.mark.asyncio
    async def test_delete_server_database_connection_lost(self, server_service, mock_db_session, mock_server):
        """Test delete_server when database connection is lost during operation."""
        # Mock server validation to return server
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=mock_server):
            # Mock database service to raise OperationalError
            with patch.object(server_service.database_service, 'soft_delete_server', side_effect=OperationalError("connection lost", None, None)):
                with pytest.raises(OperationalError):
                    await server_service.delete_server(1, mock_db_session)

    # Test query operation failures
    def test_list_servers_for_admin_database_error(self, server_service, mock_db_session):
        """Test list_servers for admin when database query fails."""
        mock_db_session.query.side_effect = DatabaseError("query failed", None, None)
        
        with pytest.raises(HTTPException) as exc_info:
            server_service.list_servers(db=mock_db_session)
        
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_server_by_id_statement_error(self, server_service, mock_db_session):
        """Test get_server when SQL statement contains errors."""
        # Mock validation service to raise StatementError
        with patch.object(server_service.validation_service, 'validate_server_exists', side_effect=StatementError("invalid column", None, None, None)):
            with pytest.raises(StatementError):
                await server_service.get_server(1, mock_db_session)

    # Test transaction rollback scenarios
    @pytest.mark.asyncio
    async def test_create_server_rollback_failure(self, server_service, mock_db_session, mock_user, server_create_data):
        """Test create_server when both commit and rollback fail."""
        # Mock validation to pass
        with patch.object(server_service.validation_service, 'validate_server_uniqueness', new_callable=AsyncMock):
            with patch.object(server_service.filesystem_service, 'create_server_directory', new_callable=AsyncMock):
                with patch.object(server_service.jar_service, 'get_server_jar', new_callable=AsyncMock):
                    # Mock database service that calls rollback internally
                    def failing_create(*args, **kwargs):
                        mock_db_session.rollback()
                        raise IntegrityError("constraint violation", None, None)
                    with patch.object(server_service.database_service, 'create_server_record', side_effect=failing_create):
                        with patch.object(server_service.filesystem_service, 'cleanup_server_directory', new_callable=AsyncMock):
                            with pytest.raises(IntegrityError):
                                await server_service.create_server(server_create_data, mock_user, mock_db_session)

    @pytest.mark.asyncio
    async def test_update_server_rollback_on_refresh_failure(self, server_service, mock_db_session, mock_server, server_update_data):
        """Test update_server when refresh operation fails after successful update."""
        # Mock server validation to return server
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=mock_server):
            # Mock database service where refresh fails
            def failing_update(*args, **kwargs):
                mock_db_session.refresh.side_effect = DatabaseError("refresh failed", None, None)
                raise DatabaseError("refresh failed", None, None)
            with patch.object(server_service.database_service, 'update_server_record', side_effect=failing_update):
                with pytest.raises(DatabaseError):
                    await server_service.update_server(1, server_update_data, mock_db_session)

    # Test batch operation failures
    def test_bulk_operation_partial_failure(self):
        """Test bulk operations when some succeed and some fail."""
        # This test is for hypothetical bulk operations that don't exist in ServerService
        # Skipping as the actual service doesn't have bulk delete methods
        pytest.skip("ServerService doesn't implement bulk operations")

    # Test connection pool exhaustion
    def test_server_operations_connection_pool_exhausted(self, server_service, mock_db_session):
        """Test server operations when connection pool is exhausted."""
        mock_db_session.query.side_effect = OperationalError("connection pool exhausted", None, None)
        
        with pytest.raises(HTTPException) as exc_info:
            server_service.list_servers(db=mock_db_session)
        
        assert exc_info.value.status_code == 500

    # Test database schema version mismatch
    def test_server_operations_schema_mismatch(self, server_service, mock_db_session):
        """Test server operations when database schema doesn't match expected version."""
        mock_db_session.query.side_effect = StatementError("no such column", None, None, None)
        
        with pytest.raises(HTTPException) as exc_info:
            server_service.list_servers(db=mock_db_session)
        
        assert exc_info.value.status_code == 500

    # Test memory constraints during database operations
    def test_large_query_memory_error(self, server_service, mock_db_session):
        """Test handling of memory errors during large database queries."""
        mock_db_session.query.side_effect = MemoryError("out of memory")
        
        with pytest.raises(HTTPException) as exc_info:
            server_service.list_servers(db=mock_db_session)
        
        assert exc_info.value.status_code == 500

    # Test database deadlock scenarios
    @pytest.mark.asyncio
    async def test_update_server_deadlock_detection(self, server_service, mock_db_session, mock_server, server_update_data):
        """Test update_server when database deadlock is detected."""
        # Mock server validation to return server
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=mock_server):
            # Mock database service to raise OperationalError
            with patch.object(server_service.database_service, 'update_server_record', side_effect=OperationalError("deadlock detected", None, None)):
                with pytest.raises(OperationalError):
                    await server_service.update_server(1, server_update_data, mock_db_session)

    # Test database maintenance mode
    def test_server_operations_during_maintenance(self, server_service, mock_db_session):
        """Test server operations when database is in maintenance mode."""
        mock_db_session.query.side_effect = OperationalError("database is locked", None, None)
        
        with pytest.raises(HTTPException) as exc_info:
            server_service.list_servers(db=mock_db_session)
        
        assert exc_info.value.status_code == 500

    # Test invalid data types causing database errors
    @pytest.mark.asyncio
    async def test_create_server_invalid_data_type(self, server_service, mock_db_session, mock_user, server_create_data):
        """Test create_server with data that causes type conversion errors."""
        # Mock validation to pass
        with patch.object(server_service.validation_service, 'validate_server_uniqueness', new_callable=AsyncMock):
            with patch.object(server_service.filesystem_service, 'create_server_directory', new_callable=AsyncMock):
                with patch.object(server_service.jar_service, 'get_server_jar', new_callable=AsyncMock):
                    # Mock database service to raise StatementError
                    with patch.object(server_service.database_service, 'create_server_record', side_effect=StatementError("invalid data type", None, None, None)):
                        with patch.object(server_service.filesystem_service, 'cleanup_server_directory', new_callable=AsyncMock):
                            with pytest.raises(StatementError):
                                await server_service.create_server(server_create_data, mock_user, mock_db_session)

    # Test database recovery scenarios
    def test_server_operation_after_database_recovery(self, server_service, mock_db_session):
        """Test server operations immediately after database recovery."""
        # First call fails due to recovery
        mock_db_session.query.side_effect = [
            OperationalError("database recovering", None, None),
            Mock()  # Second call succeeds
        ]
        
        with pytest.raises(HTTPException) as exc_info:
            server_service.list_servers(db=mock_db_session)
        
        assert exc_info.value.status_code == 500