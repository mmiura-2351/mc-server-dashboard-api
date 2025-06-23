"""
Comprehensive test coverage for TemplateService
Covers template management operations, error handling, and edge cases
"""

import tarfile
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from app.servers.models import Server, ServerType, Template
from app.services.template_service import (
    TemplateCreationError,
    TemplateError,
    TemplateService,
    template_service,
)
from app.users.models import Role, User


class TestTemplateServiceEnhancedCoverage:
    """Enhanced tests targeting uncovered lines"""

    @pytest.fixture
    def service(self):
        with patch("pathlib.Path.mkdir"):
            return TemplateService()

    @pytest.fixture
    def mock_admin_user(self):
        user = Mock(spec=User)
        user.id = 1
        user.role = Mock()
        user.role.value = "admin"
        return user

    @pytest.fixture
    def mock_operator_user(self):
        user = Mock(spec=User)
        user.id = 2
        user.role = Role.operator
        return user

    @pytest.fixture
    def mock_regular_user(self):
        user = Mock(spec=User)
        user.id = 3
        user.role = Mock()
        user.role.value = "user"
        return user

    @pytest.fixture
    def mock_server(self):
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test-server"
        server.minecraft_version = "1.20.1"
        server.server_type = ServerType.vanilla
        server.port = 25565
        server.max_memory = 1024
        server.max_players = 20
        server.directory_path = "./servers/1"
        server.owner_id = 1
        return server

    @pytest.fixture
    def mock_template(self):
        template = Mock(spec=Template)
        template.id = 1
        template.name = "test-template"
        template.description = "Test template"
        template.minecraft_version = "1.20.1"
        template.server_type = ServerType.vanilla
        template.is_public = False
        template.created_by = 1
        template.get_configuration.return_value = {"server_properties": {"motd": "test"}}
        template.get_default_groups.return_value = {}
        return template

    @pytest.fixture
    def mock_db(self):
        db = Mock(spec=Session)
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        db.refresh = Mock()
        db.query = Mock()
        return db

    # Test error handling in create_template_from_server (lines 101-106)
    @pytest.mark.asyncio
    async def test_create_template_from_server_exception_with_rollback(
        self, service, mock_server, mock_admin_user, mock_db
    ):
        """Test exception handling with database rollback in create_template_from_server"""
        # Mock server query to return mock_server
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server

        # Mock template creation to trigger the exception after template is created
        with patch("pathlib.Path.exists", return_value=True):  # Mock server dir exists
            with patch.object(
                service,
                "_create_template_files",
                side_effect=Exception("File creation failed"),
            ):
                with patch("app.services.template_service.logger") as mock_logger:
                    with pytest.raises(
                        TemplateCreationError,
                        match="Failed to create template: File creation failed",
                    ):
                        await service.create_template_from_server(
                            server_id=1,
                            name="test-template",
                            description="Test description",
                            is_public=False,
                            creator=mock_admin_user,
                            db=mock_db,
                        )

                    # Verify rollback was called (line 103)
                    mock_db.rollback.assert_called_once()
                    # Verify error was logged (line 105)
                    mock_logger.error.assert_called()

    # Test error handling in create_custom_template (lines 141-144)
    @pytest.mark.asyncio
    async def test_create_custom_template_exception_with_rollback(
        self, service, mock_admin_user, mock_db
    ):
        """Test exception handling with database rollback in create_custom_template"""
        # Mock Template constructor to raise exception
        with patch(
            "app.services.template_service.Template",
            side_effect=Exception("Template creation failed"),
        ):
            with patch("app.services.template_service.logger") as mock_logger:
                with pytest.raises(
                    TemplateCreationError,
                    match="Failed to create template: Template creation failed",
                ):
                    await service.create_custom_template(
                        name="test-template",
                        minecraft_version="1.20.1",
                        server_type=ServerType.vanilla,
                        configuration={"server_properties": {}},
                        creator=mock_admin_user,
                        db=mock_db,
                    )

                # Verify rollback was called (line 142)
                mock_db.rollback.assert_called_once()
                # Verify error was logged (line 143)
                mock_logger.error.assert_called()

    # Test _extract_server_configuration method (lines 150-197)
    @pytest.mark.asyncio
    async def test_extract_server_configuration_success(self, service, mock_server):
        """Test successful server configuration extraction"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)

            # Create server.properties file
            properties_file = server_dir / "server.properties"
            with open(properties_file, "w") as f:
                f.write("motd=Test Server\n")
                f.write("difficulty=normal\n")
                f.write("gamemode=survival\n")

            # Create some directories and files
            (server_dir / "world").mkdir()
            (server_dir / "plugins").mkdir()
            (server_dir / "config.yml").touch()

            with patch.object(
                service,
                "_parse_server_properties",
                return_value={"motd": "Test Server", "difficulty": "normal"},
            ):
                config = await service._extract_server_configuration(
                    mock_server, server_dir
                )

                assert config["metadata"]["original_server_id"] == mock_server.id
                assert config["metadata"]["original_server_name"] == mock_server.name
                assert config["metadata"]["port"] == mock_server.port
                assert config["metadata"]["max_memory"] == mock_server.max_memory
                assert config["metadata"]["max_players"] == mock_server.max_players
                assert "server_properties" in config
                assert "files" in config
                assert "directories" in config

    @pytest.mark.asyncio
    async def test_extract_server_configuration_no_properties_file(
        self, service, mock_server
    ):
        """Test server configuration extraction when server.properties doesn't exist"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            # Don't create server.properties file

            config = await service._extract_server_configuration(mock_server, server_dir)

            assert config["server_properties"] == {}
            assert config["metadata"]["original_server_id"] == mock_server.id

    # Test _parse_server_properties method (lines 211-213)
    @pytest.mark.asyncio
    async def test_parse_server_properties_success(self, service):
        """Test parsing server.properties file successfully"""
        with tempfile.TemporaryDirectory() as temp_dir:
            properties_path = Path(temp_dir) / "server.properties"
            with open(properties_path, "w") as f:
                f.write("# Minecraft server properties\n")
                f.write("motd=Test Server\n")
                f.write("difficulty=normal\n")
                f.write("gamemode=survival\n")
                f.write("max-players=20\n")

            result = await service._parse_server_properties(properties_path)

            assert result["motd"] == "Test Server"
            assert result["difficulty"] == "normal"
            assert result["gamemode"] == "survival"
            assert result["max-players"] == "20"

    @pytest.mark.asyncio
    async def test_parse_server_properties_read_error(self, service):
        """Test _parse_server_properties when file read fails"""
        with tempfile.TemporaryDirectory() as temp_dir:
            properties_path = Path(temp_dir) / "nonexistent.properties"

            # File doesn't exist, should handle the error gracefully
            result = await service._parse_server_properties(properties_path)
            assert result == {}

    # Test _create_template_files method (lines 217-248)
    @pytest.mark.asyncio
    async def test_create_template_files_success(self, service):
        """Test successful template files creation"""
        template_id = 1

        with tempfile.TemporaryDirectory() as server_temp_dir:
            server_dir = Path(server_temp_dir)

            # Create source files
            (server_dir / "server.properties").touch()
            (server_dir / "config.yml").touch()
            (server_dir / "world").mkdir()
            (server_dir / "world" / "level.dat").touch()

            with patch.object(
                service, "templates_directory", Path(server_temp_dir) / "templates"
            ):
                service.templates_directory.mkdir(exist_ok=True)

                with patch("tarfile.open") as mock_tarfile:
                    mock_tar = Mock()
                    mock_tarfile.return_value.__enter__.return_value = mock_tar

                    await service._create_template_files(template_id, server_dir)

                    # Verify tarfile operations
                    mock_tarfile.assert_called_once()
                    mock_tar.add.assert_called()

    @pytest.mark.asyncio
    async def test_create_template_files_tar_error(self, service):
        """Test _create_template_files when tar creation fails"""
        template_id = 1

        with tempfile.TemporaryDirectory() as server_temp_dir:
            server_dir = Path(server_temp_dir)

            with patch.object(
                service, "templates_directory", Path(server_temp_dir) / "templates"
            ):
                service.templates_directory.mkdir(exist_ok=True)

                with patch("tarfile.open", side_effect=Exception("Tar creation failed")):
                    with pytest.raises(Exception, match="Tar creation failed"):
                        await service._create_template_files(template_id, server_dir)

    # Test apply_template_to_server method (lines 254-281)
    @pytest.mark.asyncio
    async def test_apply_template_to_server_success(
        self, service, mock_template, mock_db
    ):
        """Test successful template application to server"""
        template_id = 1

        # Mock database query to return the template
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template

        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            template_filename = f"template_{template_id}_files.tar.gz"
            template_archive = Path(temp_dir) / template_filename

            # Create a dummy tar file
            with tarfile.open(template_archive, "w:gz") as tar:
                # Create some content to add to tar
                content_file = Path(temp_dir) / "temp_content.txt"
                content_file.write_text("test content")
                tar.add(content_file, arcname="content.txt")

            with patch.object(service, "templates_directory", Path(temp_dir)):
                with patch.object(
                    service, "_apply_server_properties"
                ) as mock_apply_props:
                    result = await service.apply_template_to_server(
                        template_id, server_dir, mock_db
                    )

                    assert result is True
                    mock_apply_props.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_template_to_server_missing_archive(
        self, service, mock_template, mock_db
    ):
        """Test template application when archive file is missing but configuration still applies"""
        template_id = 1

        # Mock database query to return the template
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template

        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)

            with patch.object(service, "templates_directory", Path(temp_dir)):
                with patch.object(
                    service, "_apply_server_properties"
                ) as mock_apply_props:
                    result = await service.apply_template_to_server(
                        template_id, server_dir, mock_db
                    )

                    # Should still return True since configuration can be applied
                    assert result is True
                    mock_apply_props.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_template_to_server_tar_extraction_error(
        self, service, mock_template, mock_db
    ):
        """Test template application when tar extraction fails"""
        template_id = 1

        # Mock database query to return the template
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template

        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            template_filename = f"template_{template_id}_files.tar.gz"
            template_archive = Path(temp_dir) / template_filename
            template_archive.touch()  # Create empty file (invalid tar)

            with patch.object(service, "templates_directory", Path(temp_dir)):
                with patch("app.services.template_service.logger") as mock_logger:
                    result = await service.apply_template_to_server(
                        template_id, server_dir, mock_db
                    )

                    assert result is False
                    mock_logger.error.assert_called()

    # Test _apply_server_properties method (lines 287-308)
    @pytest.mark.asyncio
    async def test_apply_server_properties_success(self, service):
        """Test successful server properties application"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            properties_file = server_dir / "server.properties"

            # Create initial properties file
            with open(properties_file, "w") as f:
                f.write("# Minecraft server properties\n")
                f.write("motd=Old MOTD\n")
                f.write("difficulty=easy\n")

            template_properties = {
                "motd": "New MOTD from template",
                "gamemode": "creative",
                "difficulty": "normal",
            }

            with patch.object(
                service,
                "_parse_server_properties",
                return_value={"motd": "Old MOTD", "difficulty": "easy"},
            ):
                await service._apply_server_properties(server_dir, template_properties)

                # Verify properties were updated
                with open(properties_file, "r") as f:
                    content = f.read()
                    assert "motd=New MOTD from template" in content
                    assert "gamemode=creative" in content
                    assert "difficulty=normal" in content

    @pytest.mark.asyncio
    async def test_apply_server_properties_no_existing_file(self, service):
        """Test server properties application when no existing file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            # Don't create properties file

            template_properties = {"motd": "Template MOTD", "gamemode": "survival"}

            await service._apply_server_properties(server_dir, template_properties)

            # Verify new properties file was created
            properties_file = server_dir / "server.properties"
            assert properties_file.exists()
            with open(properties_file, "r") as f:
                content = f.read()
                assert "motd=Template MOTD" in content
                assert "gamemode=survival" in content

    @pytest.mark.asyncio
    async def test_apply_server_properties_write_error(self, service):
        """Test server properties application when write fails"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)

            template_properties = {"motd": "Test"}

            with patch(
                "builtins.open", side_effect=PermissionError("Write permission denied")
            ):
                with patch("app.services.template_service.logger") as mock_logger:
                    await service._apply_server_properties(
                        server_dir, template_properties
                    )

                    mock_logger.error.assert_called()

    # Test get_template method error cases (lines 322, 326-328)
    def test_get_template_not_found(self, service, mock_regular_user, mock_db):
        """Test get_template when template not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = service.get_template(999, mock_regular_user, mock_db)
        assert result is None

    def test_get_template_access_denied(
        self, service, mock_regular_user, mock_db, mock_template
    ):
        """Test get_template when access is denied"""
        mock_template.created_by = 999  # Different user
        mock_template.is_public = False
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template

        with pytest.raises(TemplateError):
            service.get_template(1, mock_regular_user, mock_db)

    # Test list_templates filtering (lines 374-376)
    def test_list_templates_with_filters(self, service, mock_regular_user, mock_db):
        """Test list_templates with various filters"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_query.count.return_value = 0

        result = service.list_templates(
            user=mock_regular_user,
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            is_public=True,
            page=1,
            size=10,
            db=mock_db,
        )

        assert result["templates"] == []
        assert result["total"] == 0
        assert result["page"] == 1
        assert result["size"] == 10

    # Test update_template error cases (lines 390-421)
    def test_update_template_not_found(self, service, mock_admin_user, mock_db):
        """Test update_template when template not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = service.update_template(
            template_id=999, name="New Name", user=mock_admin_user, db=mock_db
        )
        assert result is None

    def test_update_template_access_denied(
        self, service, mock_regular_user, mock_db, mock_template
    ):
        """Test update_template when access is denied"""
        mock_template.created_by = 999  # Different user
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template

        with pytest.raises(TemplateError):
            service.update_template(
                template_id=1, name="New Name", user=mock_regular_user, db=mock_db
            )

    # Test delete_template error cases (lines 433, 443, 451-452, 461-464)
    def test_delete_template_not_found(self, service, mock_admin_user, mock_db):
        """Test delete_template when template not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = service.delete_template(999, mock_admin_user, mock_db)
        assert result is False

    def test_delete_template_access_denied(
        self, service, mock_regular_user, mock_db, mock_template
    ):
        """Test delete_template when access is denied"""
        mock_template.created_by = 999  # Different user
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template

        with pytest.raises(TemplateError):
            service.delete_template(1, mock_regular_user, mock_db)

    def test_delete_template_file_deletion_error(
        self, service, mock_admin_user, mock_db, mock_template
    ):
        """Test delete_template when file deletion fails"""
        mock_template.created_by = mock_admin_user.id  # Set admin as owner
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template
        mock_db.query.return_value.filter.return_value.count.return_value = (
            0  # No servers using template
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            # Set up the templates directory
            service.templates_directory = Path(temp_dir)
            template_file = service.templates_directory / "template_1_files.tar.gz"
            template_file.touch()  # Create the file

            # Mock Path.unlink method to raise an exception
            with patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")):
                with patch("app.services.template_service.logger") as mock_logger:
                    # The actual implementation catches the exception and wraps it in TemplateError
                    with pytest.raises(
                        TemplateError,
                        match="Failed to delete template: Permission denied",
                    ):
                        service.delete_template(1, mock_admin_user, mock_db)

                    # Should log the error
                    mock_logger.error.assert_called()

    # Test clone_template method (lines 494-558)
    @pytest.mark.asyncio
    async def test_clone_template_success(
        self, service, mock_admin_user, mock_db, mock_template
    ):
        """Test successful template cloning"""
        # Mock query chain for getting original template and checking existing name
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_template,  # First call: get original template
            None,  # Second call: check for existing template with same name (should return None)
        ]

        new_template = Mock()
        new_template.id = 2

        with patch("app.services.template_service.Template") as mock_template_class:
            mock_template_class.return_value = new_template

            result = await service.clone_template(
                original_template_id=1,
                name="Cloned Template",
                user=mock_admin_user,
                db=mock_db,
            )

            assert result == new_template
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_clone_template_not_found(self, service, mock_admin_user, mock_db):
        """Test clone_template when original template not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(
            TemplateError
        ):  # TemplateNotFoundError gets wrapped in TemplateError
            await service.clone_template(
                original_template_id=999,
                name="Cloned Template",
                user=mock_admin_user,
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_clone_template_access_denied(
        self, service, mock_regular_user, mock_db, mock_template
    ):
        """Test clone_template when access is denied"""
        mock_template.created_by = 999  # Different user
        mock_template.is_public = False
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template

        with pytest.raises(TemplateError):
            await service.clone_template(
                original_template_id=1,
                name="Cloned Template",
                user=mock_regular_user,
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_clone_template_creation_error(
        self, service, mock_admin_user, mock_db, mock_template
    ):
        """Test clone_template when template creation fails"""
        # Mock query chain
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_template,  # First call: get original template
            None,  # Second call: check for existing template with same name
        ]

        with patch(
            "app.services.template_service.Template",
            side_effect=Exception("Creation failed"),
        ):
            with pytest.raises(
                TemplateError
            ):  # Should raise TemplateError, not TemplateCreationError
                await service.clone_template(
                    original_template_id=1,
                    name="Cloned Template",
                    user=mock_admin_user,
                    db=mock_db,
                )

    # Test get_template_statistics method (lines 587-589)
    def test_get_template_statistics_exception(self, service, mock_regular_user, mock_db):
        """Test get_template_statistics when database query fails"""
        mock_db.query.side_effect = Exception("Database error")

        with patch("app.services.template_service.logger") as mock_logger:
            with pytest.raises(TemplateError):
                service.get_template_statistics(mock_regular_user, mock_db)

            mock_logger.error.assert_called()


class TestTemplateServicePermissionMethods:
    """Test permission checking methods"""

    @pytest.fixture
    def service(self):
        return TemplateService()

    def test_can_access_template_public_template(self, service):
        """Test _can_access_template with public template"""
        template = Mock()
        template.is_public = True
        user = Mock()

        result = service._can_access_template(template, user)
        assert result is True

    def test_can_access_template_owner(self, service):
        """Test _can_access_template with template owner"""
        template = Mock()
        template.is_public = False
        template.created_by = 1
        user = Mock()
        user.id = 1
        user.role = Mock()
        user.role.value = "user"

        result = service._can_access_template(template, user)
        assert result is True

    def test_can_access_template_admin(self, service):
        """Test _can_access_template with admin user"""
        template = Mock()
        template.is_public = False
        template.created_by = 2
        user = Mock()
        user.id = 1
        user.role = Role.admin

        result = service._can_access_template(template, user)
        assert result is True

    def test_can_access_template_denied(self, service):
        """Test _can_access_template access denied"""
        template = Mock()
        template.is_public = False
        template.created_by = 2
        user = Mock()
        user.id = 1
        user.role = Mock()
        user.role.value = "user"

        result = service._can_access_template(template, user)
        assert result is False

    def test_can_modify_template_owner(self, service):
        """Test _can_modify_template with template owner"""
        template = Mock()
        template.created_by = 1
        user = Mock()
        user.id = 1
        user.role = Mock()
        user.role.value = "user"

        result = service._can_modify_template(template, user)
        assert result is True

    def test_can_modify_template_admin(self, service):
        """Test _can_modify_template with admin user"""
        template = Mock()
        template.created_by = 2
        user = Mock()
        user.id = 1
        user.role = Role.admin

        result = service._can_modify_template(template, user)
        assert result is True

    def test_can_modify_template_denied(self, service):
        """Test _can_modify_template access denied"""
        template = Mock()
        template.created_by = 2
        user = Mock()
        user.id = 1
        user.role = Mock()
        user.role.value = "user"

        result = service._can_modify_template(template, user)
        assert result is False


class TestTemplateServiceSingleton:
    """Test service singleton instance"""

    def test_template_service_instance_exists(self):
        """Test that template_service instance is available"""
        assert template_service is not None
        assert isinstance(template_service, TemplateService)
