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
from app.servers.adapters._legacy_helpers import ServerValidationService
from app.servers.application.service import (
    ServerDatabaseService,
    ServerFileSystemService,
    ServerJarService,
    ServerSecurityValidator,
    ServerService,
)
from app.servers.domain.exceptions import UnsupportedMinecraftVersionError
from app.servers.models import Server, ServerType
from app.servers.schemas import ServerCreateRequest, ServerUpdateRequest
from app.users.domain.value_objects import Role
from app.users.models import User


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
        """Server creation with an unsupported version raises a structured error.

        Issue #33 replaced the generic ``InvalidRequestException`` with
        :class:`UnsupportedMinecraftVersionError` so the global handler
        can render an actionable ``SERVER_UNSUPPORTED_VERSION`` 400
        response. The message still names the offending version + type
        so existing UI strings continue to match.
        """
        from app.servers.domain.exceptions import UnsupportedMinecraftVersionError

        # Mock validation to pass initial checks
        server_service.validation_service.validate_server_uniqueness = AsyncMock()

        with patch(
            "app.servers.application.service.ServerSecurityValidator"
        ) as mock_validator:
            mock_validator.validate_server_name.return_value = True
            mock_validator.validate_memory_value.return_value = True

            # Mock the database version validation method to return False
            server_service._is_version_supported_db = AsyncMock(return_value=False)

            with pytest.raises(UnsupportedMinecraftVersionError) as exc_info:
                await server_service.create_server(mock_request, mock_user, mock_db)

            assert exc_info.value.error_code == "SERVER_UNSUPPORTED_VERSION"
            assert exc_info.value.version == "1.20.1"
            assert exc_info.value.server_type == "vanilla"

    @pytest.mark.asyncio
    async def test_get_server_success(self, server_service, mock_db):
        """Test successful get server (lines 639-642)"""
        mock_server = Mock()
        server_service.validation_service.validate_server_exists = Mock(
            return_value=mock_server
        )

        with patch("app.servers.application.service.ServerResponse") as mock_response:
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

        with patch(
            "app.servers.application.service.ServerSecurityValidator"
        ) as mock_validator:
            mock_validator.validate_server_name.return_value = True
            mock_validator.validate_memory_value.return_value = True

            with patch("app.servers.application.service.ServerResponse") as mock_response:
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

    @pytest.mark.asyncio
    async def test_update_server_uses_uow_when_wired(self, mock_db):
        """`update_server` routes through the UoW when DI is wired (#278)."""
        # Build a ServerService with an injected UoW; the legacy
        # database_service.update_server_record path must NOT be reached.
        fake_uow = Mock()
        service = ServerService(uow=fake_uow)
        mock_existing = Mock()
        mock_existing.port = 25565
        service.validation_service.validate_server_exists = Mock(
            return_value=mock_existing
        )
        # Stub _update_via_uow so we don't need a full SqlAlchemy UoW.
        mock_updated = Mock()
        mock_updated.directory_path = "/tmp/server"
        mock_updated.id = 1
        mock_updated.port = 25565
        mock_updated.max_players = 20
        service._update_via_uow = AsyncMock(return_value=mock_updated)
        # And stub the property-sync helper so we don't touch the FS.
        service._sync_server_properties_after_update = AsyncMock()
        # Make sure the legacy DB path is NOT called.
        service.database_service.update_server_record = Mock(
            side_effect=AssertionError("legacy path must not be used with UoW")
        )

        request = Mock(spec=ServerUpdateRequest)
        request.name = "renamed"
        request.max_memory = None
        request.max_players = None
        request.port = None
        request.server_properties = None
        request.description = None

        with patch("app.servers.application.service.ServerSecurityValidator"):
            with patch("app.servers.application.service.ServerResponse") as mock_resp:
                mock_resp.model_validate.return_value = "uow_response"
                await service.update_server(1, request, mock_db)

        service._update_via_uow.assert_awaited_once_with(1, request)
        service._sync_server_properties_after_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_server_uses_uow_when_wired(self, mock_db):
        """`delete_server` routes through the UoW when DI is wired (#278)."""

        class _FakeServersRepo:
            def __init__(self) -> None:
                self.soft_delete_called_with: list[int] = []

            async def soft_delete(self, server_id: int) -> bool:
                self.soft_delete_called_with.append(server_id)
                return True

        class _FakeUoW:
            def __init__(self) -> None:
                self.servers = _FakeServersRepo()
                self.commits = 0
                self.entered = 0

            async def __aenter__(self):
                self.entered += 1
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def commit(self):
                self.commits += 1

            async def rollback(self):
                pass

        uow = _FakeUoW()
        service = ServerService(uow=uow)
        mock_server = Mock()
        service.validation_service.validate_server_exists = Mock(return_value=mock_server)
        # Legacy path must NOT be used.
        service.database_service.soft_delete_server = Mock(
            side_effect=AssertionError("legacy path must not be used with UoW")
        )

        result = await service.delete_server(42, mock_db)

        assert result is True
        assert uow.servers.soft_delete_called_with == [42]
        assert uow.commits == 1
        assert uow.entered == 1

    @pytest.mark.asyncio
    async def test_delete_server_uow_missing_row_raises(self, mock_db):
        """If the row vanishes between validation and UoW delete, raise."""

        class _FakeServersRepo:
            async def soft_delete(self, server_id: int) -> bool:
                return False

        class _FakeUoW:
            def __init__(self) -> None:
                self.servers = _FakeServersRepo()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def commit(self):
                pass

            async def rollback(self):
                pass

        service = ServerService(uow=_FakeUoW())
        service.validation_service.validate_server_exists = Mock(return_value=Mock())

        with pytest.raises(RuntimeError, match="vanished between validation and delete"):
            await service.delete_server(99, mock_db)

    @pytest.mark.asyncio
    async def test_sync_server_properties_after_update_boolean_values(
        self, server_service, tmp_path
    ):
        """Booleans in custom_properties are written as lowercase Java literals."""
        props_file = tmp_path / "server.properties"
        props_file.write_text(
            "#Minecraft server properties\nserver-port=25565\npvp=true\n"
        )

        server = Mock(spec=Server)
        server.id = 1
        server.directory_path = str(tmp_path)
        server.port = 25565
        server.max_players = 20

        await server_service._sync_server_properties_after_update(
            server,
            custom_properties={
                "pvp": False,
                "enable_command_block": True,
                "view_distance": 12,
                "motd": "Hello",
            },
        )

        written = {}
        for line in props_file.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                written[k] = v

        assert written["pvp"] == "false"
        assert written["enable-command-block"] == "true"
        assert written["view-distance"] == "12"
        assert written["motd"] == "Hello"
        assert written["server-port"] == "25565"
        assert written["max-players"] == "20"


class TestServerValidationServiceExtended:
    """Additional tests for ServerValidationService methods"""

    @pytest.fixture
    def validation_service(self):
        return ServerValidationService()

    def test_validate_server_directory_success(self, validation_service):
        """Test successful server directory validation (lines 157-172)"""
        with patch(
            "app.servers.adapters._legacy_helpers.PathValidator"
        ) as mock_path_validator:
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
        with patch(
            "app.servers.adapters._legacy_helpers.PathValidator"
        ) as mock_path_validator:
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
    async def test_get_server_jar_unsupported_version(self, jar_service, db):
        """Test JAR service with unsupported version (lines 212-218)"""
        with patch.object(
            jar_service.version_manager, "is_version_supported", return_value=False
        ):
            with patch(
                "app.servers.adapters._legacy_helpers.handle_file_error"
            ) as mock_handle_error:
                await jar_service.get_server_jar(
                    ServerType.vanilla, "1.7.10", Path("/tmp"), db
                )

                # Should call handle_file_error due to InvalidRequestException
                mock_handle_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_server_jar_exception_handling(self, jar_service, db):
        """Test JAR service exception handling (lines 240-241)"""
        with patch.object(
            jar_service.version_manager, "is_version_supported", return_value=True
        ):
            with patch.object(
                jar_service.version_manager,
                "get_download_url",
                side_effect=Exception("Download error"),
            ):
                with patch(
                    "app.servers.adapters._legacy_helpers.handle_file_error"
                ) as mock_handle_error:
                    await jar_service.get_server_jar(
                        ServerType.vanilla, "1.20.1", Path("/tmp"), db
                    )

                    mock_handle_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_server_jar_no_download_url(self, jar_service, db):
        """Test that missing download_url raises UnsupportedMinecraftVersionError"""
        with patch.object(jar_service, "_is_version_supported_db", return_value=True):
            with patch.object(jar_service, "_get_download_url_db", return_value=None):
                with pytest.raises(UnsupportedMinecraftVersionError) as exc_info:
                    await jar_service.get_server_jar(
                        ServerType.paper, "1.21.6", Path("/tmp"), db
                    )

                assert "1.21.6" in str(exc_info.value)
                assert "paper" in str(exc_info.value)


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

        with patch("app.servers.adapters._legacy_helpers.Server") as mock_server_class:
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
