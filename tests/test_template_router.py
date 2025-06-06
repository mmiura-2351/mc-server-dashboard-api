import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.servers.models import ServerType, Template
from app.users.models import Role


class TestTemplateRouter:
    """Test cases for Template router endpoints"""

    @patch('app.services.template_service.template_service.create_template_from_server')
    def test_create_template_from_server_success(self, mock_create, client, admin_user):
        """Test creating template from server"""
        mock_template = Mock()
        mock_template.id = 1
        mock_template.name = "test-template"
        mock_template.server_type = ServerType.vanilla
        mock_create.return_value = mock_template

        template_data = {
            "server_id": 1,
            "name": "test-template",
            "description": "Test template",
            "is_public": False
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates/from-server", json=template_data)

        assert response.status_code == status.HTTP_201_CREATED
        mock_create.assert_called_once()

    @patch('app.services.template_service.template_service.create_custom_template')
    def test_create_custom_template_success(self, mock_create, client, admin_user):
        """Test creating custom template"""
        mock_template = Mock()
        mock_template.id = 1
        mock_template.name = "custom-template"
        mock_create.return_value = mock_template

        template_data = {
            "name": "custom-template",
            "minecraft_version": "1.20.1",
            "server_type": "vanilla",
            "configuration": {},
            "description": "Custom template"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates", json=template_data)

        assert response.status_code == status.HTTP_201_CREATED
        mock_create.assert_called_once()

    def test_create_template_user_forbidden(self, client, test_user):
        """Test that regular users cannot create templates"""
        template_data = {
            "name": "test-template",
            "minecraft_version": "1.20.1",
            "server_type": "vanilla",
            "configuration": {}
        }

        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.post("/api/v1/templates", json=template_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.template_service.template_service.list_templates')
    def test_list_templates_success(self, mock_list, client, admin_user):
        """Test listing templates"""
        mock_templates = [
            Mock(id=1, name="template-1", server_type=ServerType.vanilla),
            Mock(id=2, name="template-2", server_type=ServerType.paper)
        ]

        mock_list.return_value = {
            "templates": mock_templates,
            "total": 2,
            "page": 1,
            "size": 50
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/templates")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "templates" in data
        assert data["total"] == 2

    @patch('app.services.template_service.template_service.list_templates')
    def test_list_templates_with_filters(self, mock_list, client, admin_user):
        """Test listing templates with filters"""
        mock_list.return_value = {
            "templates": [],
            "total": 0,
            "page": 1,
            "size": 50
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/templates?minecraft_version=1.20.1&server_type=vanilla&is_public=true")

        assert response.status_code == status.HTTP_200_OK
        mock_list.assert_called_once()

    @patch('app.services.template_service.template_service.get_template')
    def test_get_template_success(self, mock_get, client, admin_user):
        """Test getting template by ID"""
        mock_template = Mock()
        mock_template.id = 1
        mock_template.name = "test-template"
        mock_get.return_value = mock_template

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/templates/1")

        assert response.status_code == status.HTTP_200_OK

    @patch('app.services.template_service.template_service.get_template')
    def test_get_template_not_found(self, mock_get, client, admin_user):
        """Test getting non-existent template"""
        mock_get.return_value = None

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/templates/999")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch('app.services.template_service.template_service.update_template')
    def test_update_template_success(self, mock_update, client, admin_user):
        """Test updating template"""
        mock_template = Mock()
        mock_template.id = 1
        mock_template.name = "updated-template"
        mock_update.return_value = mock_template

        update_data = {
            "name": "updated-template",
            "description": "Updated description"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.put("/api/v1/templates/1", json=update_data)

        assert response.status_code == status.HTTP_200_OK
        mock_update.assert_called_once()

    @patch('app.services.template_service.template_service.delete_template')
    def test_delete_template_success(self, mock_delete, client, admin_user):
        """Test deleting template"""
        mock_delete.return_value = True

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.delete("/api/v1/templates/1")

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @patch('app.services.template_service.template_service.delete_template')
    def test_delete_template_in_use(self, mock_delete, client, admin_user):
        """Test deleting template that's still in use"""
        from app.services.template_service import TemplateError
        mock_delete.side_effect = TemplateError("Template is in use")

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.delete("/api/v1/templates/1")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch('app.services.template_service.template_service.clone_template')
    def test_clone_template_success(self, mock_clone, client, admin_user):
        """Test cloning template"""
        mock_template = Mock()
        mock_template.id = 2
        mock_template.name = "cloned-template"
        mock_clone.return_value = mock_template

        clone_data = {
            "name": "cloned-template",
            "description": "Cloned template",
            "is_public": False
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates/1/clone", json=clone_data)

        assert response.status_code == status.HTTP_201_CREATED
        mock_clone.assert_called_once()

    @patch('app.services.template_service.template_service.get_template_statistics')
    def test_get_template_statistics(self, mock_get_stats, client, admin_user):
        """Test getting template statistics"""
        mock_get_stats.return_value = {
            "total_templates": 5,
            "public_templates": 2,
            "user_templates": 3,
            "server_type_distribution": {
                "vanilla": 2,
                "paper": 2,
                "forge": 1
            }
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/templates/statistics")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_templates"] == 5

    def test_template_access_control(self, client, test_user, admin_user):
        """Test template access control"""
        from app.services.template_service import TemplateAccessError

        # Test that user cannot access private template
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            with patch('app.services.template_service.template_service.get_template') as mock_get:
                mock_get.side_effect = TemplateAccessError("Access denied")
                response = client.get("/api/v1/templates/1")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_template_operations_require_authentication(self, client):
        """Test that template operations require authentication"""
        response = client.get("/api/v1/templates")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.post("/api/v1/templates", json={
            "name": "test",
            "minecraft_version": "1.20.1",
            "server_type": "vanilla",
            "configuration": {}
        })
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_template_validation_errors(self, client, admin_user):
        """Test template validation errors"""
        # Missing required fields
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates", json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Invalid server type
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates", json={
                "name": "test",
                "minecraft_version": "1.20.1",
                "server_type": "invalid",
                "configuration": {}
            })
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_template_from_server_validation(self, client, admin_user):
        """Test creating template from server validation"""
        # Missing server_id
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates/from-server", json={
                "name": "test-template"
            })
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Empty name
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates/from-server", json={
                "server_id": 1,
                "name": ""
            })
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_clone_template_validation(self, client, admin_user):
        """Test template cloning validation"""
        # Missing name
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates/1/clone", json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Empty name
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates/1/clone", json={"name": ""})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('app.services.template_service.template_service.create_custom_template')
    def test_template_error_handling(self, mock_create, client, admin_user):
        """Test template creation error handling"""
        from app.services.template_service import TemplateCreationError
        
        mock_create.side_effect = TemplateCreationError("Failed to create template")

        template_data = {
            "name": "test-template",
            "minecraft_version": "1.20.1",
            "server_type": "vanilla",
            "configuration": {}
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates", json=template_data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_template_pagination(self, client, admin_user):
        """Test template listing pagination"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.template_service.template_service.list_templates') as mock_list:
                mock_list.return_value = {
                    "templates": [],
                    "total": 50,
                    "page": 2,
                    "size": 20
                }
                response = client.get("/api/v1/templates?page=2&size=20")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["page"] == 2
        assert data["size"] == 20

    @patch('app.services.template_service.template_service.update_template')
    def test_update_template_not_found(self, mock_update, client, admin_user):
        """Test updating non-existent template"""
        mock_update.return_value = None

        update_data = {"name": "updated-name"}

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.put("/api/v1/templates/999", json=update_data)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_template_configuration_validation(self, client, admin_user):
        """Test template configuration validation"""
        # Invalid configuration format
        template_data = {
            "name": "test-template",
            "minecraft_version": "1.20.1",
            "server_type": "vanilla",
            "configuration": "invalid"  # Should be object
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/templates", json=template_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY