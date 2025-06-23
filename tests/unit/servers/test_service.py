"""
Test coverage for app/servers/service.py
Focus on critical methods to improve coverage toward 100%
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.exceptions import (
    ConflictException,
    InvalidRequestException,
    ServerNotFoundException,
)
from app.servers.models import Server, ServerType
from app.servers.schemas import ServerCreateRequest, ServerUpdateRequest
from app.servers.service import (
    ServerDatabaseService,
    ServerFileSystemService,
    ServerJarService,
    ServerSecurityValidator,
    ServerService,
    ServerTemplateService,
    ServerValidationService,
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
    async def test_validate_server_uniqueness_name_conflict(
        self, validation_service, mock_db
    ):
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
    async def test_create_server_unsupported_version(
        self, server_service, mock_request, mock_user, mock_db
    ):
        """Test server creation with unsupported version (lines 582-588)"""
        # Mock validation to pass initial checks
        server_service.validation_service.validate_server_uniqueness = AsyncMock()

        with patch("app.servers.service.ServerSecurityValidator") as mock_validator:
            mock_validator.validate_server_name.return_value = True
            mock_validator.validate_memory_value.return_value = True

            with patch(
                "app.servers.service.minecraft_version_manager"
            ) as mock_version_manager:
                mock_version_manager.is_version_supported.return_value = False

                with pytest.raises(InvalidRequestException) as exc_info:
                    await server_service.create_server(mock_request, mock_user, mock_db)

                assert "Version 1.20.1 is not supported for vanilla" in str(
                    exc_info.value
                )

    @pytest.mark.asyncio
    async def test_get_server_success(self, server_service, mock_db):
        """Test successful get server (lines 639-642)"""
        mock_server = Mock()
        server_service.validation_service.validate_server_exists = Mock(
            return_value=mock_server
        )

        with patch("app.servers.service.ServerResponse") as mock_response:
            mock_response.model_validate.return_value = "server_response"

            result = await server_service.get_server(1, mock_db)

            server_service.validation_service.validate_server_exists.assert_called_once_with(
                1, mock_db
            )
            mock_response.model_validate.assert_called_once_with(mock_server)

    @pytest.mark.asyncio
    async def test_update_server_success(self, server_service, mock_db):
        """Test successful server update (lines 644-657)"""
        mock_server = Mock()
        mock_server.max_players = 20  # Add max_players attribute
        server_service.validation_service.validate_server_exists = Mock(
            return_value=mock_server
        )

        mock_updated_server = Mock()
        server_service.database_service.update_server_record = Mock(
            return_value=mock_updated_server
        )

        request = Mock(spec=ServerUpdateRequest)
        request.name = "updated-server"
        request.max_memory = 2048
        request.max_players = None  # Add max_players attribute
        request.port = None  # Add port attribute
        request.server_properties = None  # Add server_properties attribute

        with patch("app.servers.service.ServerSecurityValidator") as mock_validator:
            mock_validator.validate_server_name.return_value = True
            mock_validator.validate_memory_value.return_value = True

            with patch("app.servers.service.ServerResponse") as mock_response:
                mock_response.model_validate.return_value = "updated_response"

                result = await server_service.update_server(1, request, mock_db)

                server_service.validation_service.validate_server_exists.assert_called_once_with(
                    1, mock_db
                )
                mock_validator.validate_server_name.assert_called_once_with(
                    "updated-server"
                )
                mock_validator.validate_memory_value.assert_called_once_with(2048)

    @pytest.mark.asyncio
    async def test_delete_server_success(self, server_service, mock_db):
        """Test successful server deletion (lines 659-663)"""
        mock_server = Mock()
        server_service.validation_service.validate_server_exists = Mock(
            return_value=mock_server
        )
        server_service.database_service.soft_delete_server = Mock()

        result = await server_service.delete_server(1, mock_db)

        assert result is True
        server_service.validation_service.validate_server_exists.assert_called_once_with(
            1, mock_db
        )
        server_service.database_service.soft_delete_server.assert_called_once_with(
            mock_server, mock_db
        )


class TestServerValidationServiceExtended:
    """Additional tests for ServerValidationService methods"""

    @pytest.fixture
    def validation_service(self):
        return ServerValidationService()

    def test_validate_server_directory_success(self, validation_service):
        """Test successful server directory validation (lines 157-172)"""
        with patch("app.servers.service.PathValidator") as mock_path_validator:
            mock_server_dir = Mock()
            mock_server_dir.exists.return_value = False
            mock_path_validator.create_safe_server_directory.return_value = (
                mock_server_dir
            )

            result = validation_service.validate_server_directory("test-server")

            assert result == mock_server_dir
            mock_path_validator.create_safe_server_directory.assert_called_once()

    def test_validate_server_directory_exists(self, validation_service):
        """Test server directory already exists (lines 168-171)"""
        with patch("app.servers.service.PathValidator") as mock_path_validator:
            mock_server_dir = Mock()
            mock_server_dir.exists.return_value = True
            mock_path_validator.create_safe_server_directory.return_value = (
                mock_server_dir
            )

            with pytest.raises(ConflictException) as exc_info:
                validation_service.validate_server_directory("existing-server")

            assert "Server directory for 'existing-server' already exists" in str(
                exc_info.value
            )

    def test_validate_server_name_basic_empty(self, validation_service):
        """Test basic server name validation with empty string (lines 178-179)"""
        from app.core.security import SecurityError

        with pytest.raises(SecurityError) as exc_info:
            validation_service._validate_server_name_basic("")

        assert "Server name must be a non-empty string" in str(exc_info.value)

    def test_validate_server_name_basic_none(self, validation_service):
        """Test basic server name validation with None (lines 178-179)"""
        from app.core.security import SecurityError

        with pytest.raises(SecurityError) as exc_info:
            validation_service._validate_server_name_basic(None)

        assert "Server name must be a non-empty string" in str(exc_info.value)


class TestServerJarServiceExtended:
    """Additional tests for ServerJarService methods"""

    @pytest.fixture
    def jar_service(self):
        return ServerJarService()

    @pytest.mark.asyncio
    async def test_get_server_jar_unsupported_version(self, jar_service):
        """Test JAR service with unsupported version (lines 212-218)"""
        with patch.object(
            jar_service.version_manager, "is_version_supported", return_value=False
        ):
            with patch("app.servers.service.handle_file_error") as mock_handle_error:
                await jar_service.get_server_jar(
                    ServerType.vanilla, "1.7.10", Path("/tmp")
                )

                # Should call handle_file_error due to InvalidRequestException
                mock_handle_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_server_jar_exception_handling(self, jar_service):
        """Test JAR service exception handling (lines 240-241)"""
        with patch.object(
            jar_service.version_manager, "is_version_supported", return_value=True
        ):
            with patch.object(
                jar_service.version_manager,
                "get_download_url",
                side_effect=Exception("Download error"),
            ):
                with patch("app.servers.service.handle_file_error") as mock_handle_error:
                    await jar_service.get_server_jar(
                        ServerType.vanilla, "1.20.1", Path("/tmp")
                    )

                    mock_handle_error.assert_called_once()


class TestServerFileSystemServiceExtended:
    """Additional tests for ServerFileSystemService methods"""

    @pytest.fixture
    def filesystem_service(self):
        return ServerFileSystemService()

    @pytest.mark.asyncio
    async def test_generate_server_files_success(self, filesystem_service):
        """Test server files generation (lines 335-352)"""
        mock_server = Mock()
        mock_server.id = 1
        mock_server.name = "test-server"
        mock_request = Mock()
        mock_server_dir = Path("/tmp/test")

        filesystem_service._generate_server_properties = AsyncMock()
        filesystem_service._generate_eula_file = AsyncMock()
        filesystem_service._generate_startup_script = AsyncMock()

        await filesystem_service.generate_server_files(
            mock_server, mock_request, mock_server_dir
        )

        filesystem_service._generate_server_properties.assert_called_once()
        filesystem_service._generate_eula_file.assert_called_once()
        filesystem_service._generate_startup_script.assert_called_once()


class TestServerDatabaseService:
    """Tests for ServerDatabaseService methods"""

    @pytest.fixture
    def database_service(self):
        return ServerDatabaseService()

    def test_create_server_record_success(self, database_service):
        """Test server record creation (lines 456-488)"""
        mock_request = Mock()
        mock_request.name = "test-server"
        mock_request.description = "Test description"
        mock_request.minecraft_version = "1.20.1"
        mock_request.server_type = ServerType.vanilla
        mock_request.port = 25565
        mock_request.max_memory = 1024
        mock_request.max_players = 20
        mock_request.server_properties = {}

        mock_owner = Mock()
        mock_owner.id = 1

        server_dir = "/tmp/test-server"
        mock_db = Mock()

        with patch("app.servers.service.Server") as mock_server_class:
            mock_server = Mock()
            mock_server_class.return_value = mock_server

            result = database_service.create_server_record(
                mock_request, mock_owner, server_dir, mock_db
            )

            assert result == mock_server
            mock_db.add.assert_called_once_with(mock_server)
            mock_db.commit.assert_called_once()
            mock_db.refresh.assert_called_once_with(mock_server)

    def test_soft_delete_server_success(self, database_service):
        """Test server soft deletion (lines 531-545)"""
        mock_server = Mock()
        mock_server.is_deleted = False
        mock_db = Mock()

        database_service.soft_delete_server(mock_server, mock_db)

        assert mock_server.is_deleted is True
        mock_db.commit.assert_called_once()


class TestServerTemplateService:
    """Tests for ServerTemplateService methods"""

    @pytest.fixture
    def template_service(self):
        filesystem_service = Mock()
        return ServerTemplateService(filesystem_service)

    @pytest.mark.asyncio
    async def test_apply_template_success(self, template_service):
        """Test template application (lines 529-557)"""
        mock_server = Mock()
        mock_server.id = 1
        mock_server.directory_path = "/tmp/server"

        mock_template = Mock()
        mock_template.id = 1
        mock_template.name = "test-template"
        mock_template.file_path = "/tmp/template.tar.gz"

        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template

        template_service._extract_template_files = AsyncMock()

        with patch("app.servers.service.Path") as mock_path:
            mock_template_path = Mock()
            mock_template_path.exists.return_value = True
            mock_path.return_value = mock_template_path

            await template_service.apply_template(mock_server, 1, mock_db)

            template_service._extract_template_files.assert_called_once()
