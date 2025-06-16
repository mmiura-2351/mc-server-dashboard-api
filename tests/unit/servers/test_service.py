"""
Test coverage for app/servers/service.py
Focus on critical methods to improve coverage toward 100%
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
import tempfile
import shutil

from app.core.exceptions import InvalidRequestException, ConflictException, ServerNotFoundException
from app.servers.models import Server, ServerType, ServerStatus, Template
from app.servers.schemas import ServerCreateRequest, ServerUpdateRequest
from app.servers.service import (
    ServerSecurityValidator,
    ServerValidationService,
    ServerJarService,
    ServerFileSystemService,
    ServerDatabaseService,
    ServerTemplateService,
    ServerService
)
from app.users.models import Role, User


class TestServerSecurityValidator:
    """Test cases for ServerSecurityValidator"""

    def test_validate_memory_value_valid(self):
        """Test valid memory values"""
        assert ServerSecurityValidator.validate_memory_value(512) is True
        assert ServerSecurityValidator.validate_memory_value(1024) is True
        assert ServerSecurityValidator.validate_memory_value(8192) is True

    def test_validate_memory_value_non_integer(self):
        """Test non-integer memory value (line 45-46)"""
        with pytest.raises(InvalidRequestException) as exc_info:
            ServerSecurityValidator.validate_memory_value("1024")
        assert "Memory value must be an integer" in str(exc_info.value)

    def test_validate_memory_value_negative(self):
        """Test negative memory value (line 47-48)"""
        with pytest.raises(InvalidRequestException) as exc_info:
            ServerSecurityValidator.validate_memory_value(-512)
        assert "Memory value must be positive" in str(exc_info.value)

    def test_validate_memory_value_too_large(self):
        """Test memory value exceeding maximum (line 49-52)"""
        with pytest.raises(InvalidRequestException) as exc_info:
            ServerSecurityValidator.validate_memory_value(40960)  # > 32GB
        assert "Memory value exceeds maximum allowed (32768MB)" in str(exc_info.value)

    def test_validate_server_name_valid(self):
        """Test valid server names"""
        assert ServerSecurityValidator.validate_server_name("test-server") is True
        assert ServerSecurityValidator.validate_server_name("my_server_123") is True

    def test_validate_server_name_empty(self):
        """Test empty server name validation (line 78-79)"""
        with pytest.raises(InvalidRequestException) as exc_info:
            ServerSecurityValidator.validate_server_name("")
        assert "Server name cannot be empty" in str(exc_info.value)

    def test_validate_server_name_invalid_characters(self):
        """Test server name with invalid characters (line 82-83)"""
        invalid_names = ["server@name", "server#name", "server$name", "server%name"]
        for name in invalid_names:
            with pytest.raises(InvalidRequestException) as exc_info:
                ServerSecurityValidator.validate_server_name(name)
            assert "Server name contains invalid characters" in str(exc_info.value)

    def test_validate_jar_filename_valid(self):
        """Test valid JAR filename validation (line 56-73)"""
        assert ServerSecurityValidator.validate_jar_filename("server.jar") is True
        assert ServerSecurityValidator.validate_jar_filename("paper-1.20.1.jar") is True

    def test_validate_jar_filename_empty(self):
        """Test empty JAR filename validation (line 58-59)"""
        with pytest.raises(InvalidRequestException) as exc_info:
            ServerSecurityValidator.validate_jar_filename("")
        assert "JAR filename cannot be empty" in str(exc_info.value)

    def test_validate_jar_filename_invalid_format(self):
        """Test invalid JAR filename format (line 62-63)"""
        with pytest.raises(InvalidRequestException) as exc_info:
            ServerSecurityValidator.validate_jar_filename("server.txt")
        assert "Invalid JAR filename format" in str(exc_info.value)

    def test_validate_jar_filename_path_traversal(self):
        """Test JAR filename path traversal prevention (line 62-67)"""
        with pytest.raises(InvalidRequestException) as exc_info:
            ServerSecurityValidator.validate_jar_filename("../server.jar")
        # Format check happens first, so we get format error instead of path separator error
        assert "Invalid JAR filename format" in str(exc_info.value)

    def test_validate_java_path_valid(self):
        """Test valid Java path validation (line 92-113)"""
        assert ServerSecurityValidator.validate_java_path("/usr/bin/java") is True

    def test_validate_java_path_empty(self):
        """Test empty Java path validation (line 94-95)"""
        with pytest.raises(InvalidRequestException) as exc_info:
            ServerSecurityValidator.validate_java_path("")
        assert "Java path cannot be empty" in str(exc_info.value)

    def test_validate_java_path_relative(self):
        """Test relative Java path validation (line 110-111)"""
        with pytest.raises(InvalidRequestException) as exc_info:
            ServerSecurityValidator.validate_java_path("java")
        assert "Java path must be absolute" in str(exc_info.value)


class TestServerValidationService:
    """Test cases for ServerValidationService"""

    @pytest.fixture
    def validation_service(self):
        return ServerValidationService()

    @pytest.fixture
    def mock_db(self):
        db = Mock()
        db.query.return_value = db
        db.filter.return_value = db
        db.first.return_value = None
        return db

    @pytest.mark.asyncio
    async def test_validate_server_uniqueness_success(self, validation_service, mock_db):
        """Test successful server uniqueness validation (lines 128-145)"""
        request = Mock()
        request.name = "unique-server"

        # Mock no existing server
        mock_db.first.return_value = None

        # Should not raise any exception
        await validation_service.validate_server_uniqueness(request, mock_db)

    @pytest.mark.asyncio
    async def test_validate_server_uniqueness_name_conflict(self, validation_service, mock_db):
        """Test server name conflict validation (lines 143-144)"""
        request = Mock()
        request.name = "existing-server"

        # Mock existing server with same name
        existing_server = Mock()
        mock_db.first.return_value = existing_server

        with pytest.raises(ConflictException) as exc_info:
            await validation_service.validate_server_uniqueness(request, mock_db)
        
        assert "Server with name 'existing-server' already exists" in str(exc_info.value)

    def test_validate_server_exists_success(self, validation_service, mock_db):
        """Test successful server existence validation (lines 146-155)"""
        server = Mock(spec=Server)
        mock_db.first.return_value = server

        result = validation_service.validate_server_exists(1, mock_db)
        assert result == server

    def test_validate_server_exists_not_found(self, validation_service, mock_db):
        """Test server not found validation (lines 153-154)"""
        mock_db.first.return_value = None

        with pytest.raises(ServerNotFoundException):
            validation_service.validate_server_exists(999, mock_db)


class TestServerService:
    """Test cases for main ServerService class - focus on critical uncovered methods"""

    @pytest.fixture
    def server_service(self):
        return ServerService()

    @pytest.fixture
    def mock_request(self):
        request = Mock(spec=ServerCreateRequest)
        request.name = "test-server"
        request.max_memory = 1024
        request.minecraft_version = "1.20.1"
        request.server_type = ServerType.vanilla
        request.port = 25565
        request.max_players = 20
        request.template_id = None
        request.attach_groups = None
        return request

    @pytest.fixture
    def mock_user(self):
        user = Mock(spec=User)
        user.id = 1
        user.username = "testuser"
        user.role = Role.admin
        return user

    @pytest.fixture
    def mock_db(self):
        return Mock()

    @pytest.mark.asyncio
    async def test_create_server_unsupported_version(self, server_service, mock_request, mock_user, mock_db):
        """Test server creation with unsupported version (lines 582-588)"""
        # Mock validation to pass initial checks
        server_service.validation_service.validate_server_uniqueness = AsyncMock()
        
        with patch('app.servers.service.ServerSecurityValidator') as mock_validator:
            mock_validator.validate_server_name.return_value = True
            mock_validator.validate_memory_value.return_value = True
            
            with patch('app.servers.service.minecraft_version_manager') as mock_version_manager:
                mock_version_manager.is_version_supported.return_value = False

                with pytest.raises(InvalidRequestException) as exc_info:
                    await server_service.create_server(mock_request, mock_user, mock_db)
                
                assert "Version 1.20.1 is not supported for vanilla" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_server_success(self, server_service, mock_db):
        """Test successful get server (lines 639-642)"""
        mock_server = Mock()
        server_service.validation_service.validate_server_exists = Mock(return_value=mock_server)

        with patch('app.servers.service.ServerResponse') as mock_response:
            mock_response.model_validate.return_value = "server_response"
            
            result = await server_service.get_server(1, mock_db)
            
            server_service.validation_service.validate_server_exists.assert_called_once_with(1, mock_db)
            mock_response.model_validate.assert_called_once_with(mock_server)

    @pytest.mark.asyncio
    async def test_update_server_success(self, server_service, mock_db):
        """Test successful server update (lines 644-657)"""
        mock_server = Mock()
        server_service.validation_service.validate_server_exists = Mock(return_value=mock_server)
        
        mock_updated_server = Mock()
        server_service.database_service.update_server_record = Mock(return_value=mock_updated_server)

        request = Mock(spec=ServerUpdateRequest)
        request.name = "updated-server"
        request.max_memory = 2048

        with patch('app.servers.service.ServerSecurityValidator') as mock_validator:
            mock_validator.validate_server_name.return_value = True
            mock_validator.validate_memory_value.return_value = True
            
            with patch('app.servers.service.ServerResponse') as mock_response:
                mock_response.model_validate.return_value = "updated_response"

                result = await server_service.update_server(1, request, mock_db)
                
                server_service.validation_service.validate_server_exists.assert_called_once_with(1, mock_db)
                mock_validator.validate_server_name.assert_called_once_with("updated-server")
                mock_validator.validate_memory_value.assert_called_once_with(2048)

    @pytest.mark.asyncio
    async def test_delete_server_success(self, server_service, mock_db):
        """Test successful server deletion (lines 659-663)"""
        mock_server = Mock()
        server_service.validation_service.validate_server_exists = Mock(return_value=mock_server)
        server_service.database_service.soft_delete_server = Mock()

        result = await server_service.delete_server(1, mock_db)
        
        assert result is True
        server_service.validation_service.validate_server_exists.assert_called_once_with(1, mock_db)
        server_service.database_service.soft_delete_server.assert_called_once_with(mock_server, mock_db)