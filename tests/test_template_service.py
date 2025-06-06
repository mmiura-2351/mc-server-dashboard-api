import pytest
from unittest.mock import Mock, patch, mock_open
from pathlib import Path

from app.services.template_service import (
    TemplateService,
    TemplateError,
    TemplateNotFoundError,
    TemplateCreationError,
    TemplateAccessError,
    template_service
)
from app.servers.models import Server, ServerType, Template
from app.users.models import User, Role


class TestTemplateServiceExceptions:
    """Test custom exception classes"""
    
    def test_template_error(self):
        error = TemplateError("test error")
        assert str(error) == "test error"
        assert isinstance(error, Exception)
    
    def test_template_not_found_error(self):
        error = TemplateNotFoundError("template not found")
        assert str(error) == "template not found"
        assert isinstance(error, TemplateError)
    
    def test_template_creation_error(self):
        error = TemplateCreationError("creation failed")
        assert str(error) == "creation failed"
        assert isinstance(error, TemplateError)
    
    def test_template_access_error(self):
        error = TemplateAccessError("access denied")
        assert str(error) == "access denied"
        assert isinstance(error, TemplateError)


class TestTemplateService:
    """Test TemplateService class"""
    
    @pytest.fixture
    def service(self):
        with patch('pathlib.Path.mkdir'):
            return TemplateService()
    
    @pytest.fixture
    def mock_user(self):
        user = Mock(spec=User)
        user.id = 1
        user.username = "testuser"
        user.role = Mock()
        user.role.value = "user"
        return user
    
    @pytest.fixture
    def mock_admin(self):
        admin = Mock(spec=User)
        admin.id = 2
        admin.username = "admin"
        admin.role = Mock()
        admin.role.value = "admin"
        return admin
    
    @pytest.fixture
    def mock_server(self):
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test_server"
        server.minecraft_version = "1.20.1"
        server.server_type = ServerType.vanilla
        server.directory_path = "servers/test_server"
        server.port = 25565
        server.max_memory = 4096
        server.max_players = 20
        return server
    
    @pytest.fixture
    def mock_template(self):
        template = Mock(spec=Template)
        template.id = 1
        template.name = "test_template"
        template.description = "Test template"
        template.minecraft_version = "1.20.1"
        template.server_type = ServerType.vanilla
        template.created_by = 1
        template.is_public = False
        template.configuration = {"server_properties": {"server-port": "25565"}}
        template.default_groups = {"op_groups": [], "whitelist_groups": []}
        return template
    
    @pytest.fixture
    def mock_db(self):
        return Mock()
    
    def test_init(self, service):
        """Test TemplateService initialization"""
        assert service.templates_directory == Path("templates")
    
    @pytest.mark.asyncio
    async def test_create_template_from_server_server_not_found(self, service, mock_user, mock_db):
        """Test create_template_from_server when server not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(TemplateCreationError):
            await service.create_template_from_server(
                server_id=999,
                name="test_template",
                creator=mock_user,
                db=mock_db
            )
    
    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    async def test_create_template_from_server_directory_not_found(self, mock_exists, service, mock_server, mock_user, mock_db):
        """Test create_template_from_server when server directory not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = False
        
        with pytest.raises(TemplateCreationError):
            await service.create_template_from_server(
                server_id=1,
                name="test_template",
                creator=mock_user,
                db=mock_db
            )
    
    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    async def test_create_template_from_server_success(self, mock_exists, service, mock_server, mock_user, mock_db):
        """Test successful create_template_from_server"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = True
        
        mock_template = Mock()
        mock_template.id = 1
        
        with patch.object(service, '_extract_server_configuration', return_value={"test": "config"}):
            with patch.object(service, '_create_template_files'):
                result = await service.create_template_from_server(
                    server_id=1,
                    name="test_template",
                    creator=mock_user,
                    db=mock_db
                )
                
                # Verify the method was called successfully
                mock_db.add.assert_called_once()
                mock_db.commit.assert_called_once()
                mock_db.refresh.assert_called_once()
                
                # Check if result is a Template instance
                assert hasattr(result, 'name')
                assert hasattr(result, 'created_by')
    
    @pytest.mark.asyncio
    async def test_create_custom_template_success(self, service, mock_user, mock_db):
        """Test successful create_custom_template"""
        mock_template = Mock()
        mock_template.id = 1
        
        configuration = {"server_properties": {"server-port": "25565"}}
        
        result = await service.create_custom_template(
            name="custom_template",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            configuration=configuration,
            creator=mock_user,
            db=mock_db
        )
        
        # Verify the method was called successfully
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()
        
        # Check if result is a Template instance
        assert hasattr(result, 'name')
        assert hasattr(result, 'created_by')
    
    @pytest.mark.asyncio
    async def test_parse_server_properties_success(self, service):
        """Test _parse_server_properties success"""
        properties_content = """# Minecraft server properties
server-port=25565
max-players=20
gamemode=survival
"""
        properties_path = Path("server.properties")
        
        with patch('builtins.open', mock_open(read_data=properties_content)):
            result = await service._parse_server_properties(properties_path)
            
            assert result["server-port"] == "25565"
            assert result["max-players"] == "20"
            assert result["gamemode"] == "survival"
    
    def test_get_template_success(self, service, mock_template, mock_user, mock_db):
        """Test get_template success"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template
        mock_template.created_by = mock_user.id
        
        result = service.get_template(template_id=1, user=mock_user, db=mock_db)
        
        assert result == mock_template
    
    def test_get_template_not_found(self, service, mock_user, mock_db):
        """Test get_template when template not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        result = service.get_template(template_id=999, user=mock_user, db=mock_db)
        
        assert result is None
    
    def test_list_templates_user_access(self, service, mock_user, mock_db):
        """Test list_templates with regular user access"""
        mock_templates = [Mock()]
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = mock_templates
        mock_query.count.return_value = 1
        
        result = service.list_templates(user=mock_user, db=mock_db)
        
        assert result["templates"] == mock_templates
        assert result["total"] == 1
        assert result["page"] == 1
        assert result["size"] == 50
    
    def test_delete_template_success(self, service, mock_template, mock_user, mock_db):
        """Test delete_template success"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template
        mock_template.created_by = mock_user.id
        mock_db.query.return_value.filter.return_value.count.return_value = 0  # No servers using template
        
        with patch('pathlib.Path.exists', return_value=False):
            result = service.delete_template(template_id=1, user=mock_user, db=mock_db)
            
            assert result is True
            mock_db.delete.assert_called_once_with(mock_template)
            mock_db.commit.assert_called_once()
    
    def test_delete_template_not_found(self, service, mock_user, mock_db):
        """Test delete_template when template not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        result = service.delete_template(template_id=999, user=mock_user, db=mock_db)
        
        assert result is False
    
    def test_can_access_template_owner(self, service, mock_template, mock_user):
        """Test _can_access_template for template owner"""
        mock_template.created_by = mock_user.id
        mock_template.is_public = False
        
        result = service._can_access_template(mock_template, mock_user)
        assert result is True
    
    def test_can_access_template_public(self, service, mock_template, mock_user):
        """Test _can_access_template for public template"""
        mock_template.created_by = 999  # Different user
        mock_template.is_public = True
        
        result = service._can_access_template(mock_template, mock_user)
        assert result is True
    
    def test_can_access_template_admin(self, service, mock_template, mock_admin):
        """Test _can_access_template for admin user"""
        mock_template.created_by = 999  # Different user
        mock_template.is_public = False
        
        result = service._can_access_template(mock_template, mock_admin)
        assert result is True
    
    def test_can_access_template_denied(self, service, mock_template, mock_user):
        """Test _can_access_template denied"""
        mock_template.created_by = 999  # Different user
        mock_template.is_public = False
        
        result = service._can_access_template(mock_template, mock_user)
        assert result is False
    
    def test_can_modify_template_owner(self, service, mock_template, mock_user):
        """Test _can_modify_template for template owner"""
        mock_template.created_by = mock_user.id
        
        result = service._can_modify_template(mock_template, mock_user)
        assert result is True
    
    def test_can_modify_template_admin(self, service, mock_template, mock_admin):
        """Test _can_modify_template for admin user"""
        mock_template.created_by = 999  # Different user
        
        result = service._can_modify_template(mock_template, mock_admin)
        assert result is True
    
    def test_can_modify_template_denied(self, service, mock_template, mock_user):
        """Test _can_modify_template denied"""
        mock_template.created_by = 999  # Different user
        
        result = service._can_modify_template(mock_template, mock_user)
        assert result is False
    
    def test_get_template_statistics(self, service, mock_user, mock_db):
        """Test get_template_statistics"""
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.count.side_effect = [10, 5, 3, 2, 1, 0, 0]  # total, public, user, vanilla, forge, fabric, modded
        
        result = service.get_template_statistics(user=mock_user, db=mock_db)
        
        assert result["total_templates"] == 10
        assert result["public_templates"] == 5
        assert result["user_templates"] == 3
        assert "server_type_distribution" in result


def test_global_template_service_instance():
    """Test that global template_service instance exists"""
    assert template_service is not None
    assert isinstance(template_service, TemplateService)