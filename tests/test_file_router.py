import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi import status
from fastapi.testclient import TestClient
from io import BytesIO

from app.main import app
from app.types import FileType
from app.users.models import Role


class TestFileRouter:
    """Test cases for File router endpoints"""

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.get_server_files')
    def test_get_server_files_success(self, mock_get_files, mock_check_access, client, admin_user):
        """Test getting server files"""
        mock_check_access.return_value = Mock()
        mock_files = [
            {
                "name": "server.properties",
                "path": "server.properties",
                "type": FileType.config,
                "is_directory": False,
                "size": 1024,
                "permissions": {"readable": True, "writable": True}
            },
            {
                "name": "world",
                "path": "world",
                "type": FileType.directory,
                "is_directory": True,
                "size": None,
                "permissions": {"readable": True, "writable": True}
            }
        ]
        mock_get_files.return_value = mock_files

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/1/files")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "files" in data
        assert len(data["files"]) == 2

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.get_server_files')
    def test_get_server_files_with_filters(self, mock_get_files, mock_check_access, client, admin_user):
        """Test getting server files with filters"""
        mock_check_access.return_value = Mock()
        mock_get_files.return_value = []

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/1/files?path=world&file_type=config")

        assert response.status_code == status.HTTP_200_OK
        mock_get_files.assert_called_once()

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.read_file')
    def test_read_file_success(self, mock_read_file, mock_check_access, client, admin_user):
        """Test reading file content"""
        mock_check_access.return_value = Mock()
        mock_read_file.return_value = "server-port=25565\nmax-players=20"

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/1/files/read?file_path=server.properties")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "content" in data

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.write_file')
    def test_write_file_success(self, mock_write_file, mock_check_access, client, admin_user):
        """Test writing file content"""
        mock_check_access.return_value = Mock()
        mock_write_file.return_value = {
            "message": "File updated successfully",
            "file": {"name": "server.properties"},
            "backup_created": True
        }

        write_data = {
            "file_path": "server.properties",
            "content": "server-port=25565\nmax-players=30",
            "create_backup": True
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers/1/files/write", json=write_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "File updated successfully"

    def test_write_file_user_forbidden_restricted(self, client, test_user):
        """Test that regular users cannot write restricted files"""
        write_data = {
            "file_path": "ops.json",
            "content": "[]"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            with patch('app.services.authorization_service.authorization_service.check_server_access'):
                with patch('app.services.file_management_service.file_management_service.write_file') as mock_write:
                    from fastapi import HTTPException
                    mock_write.side_effect = HTTPException(status_code=403, detail="Insufficient permissions")
                    response = client.post("/api/v1/servers/1/files/write", json=write_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.delete_file')
    def test_delete_file_success(self, mock_delete_file, mock_check_access, client, admin_user):
        """Test deleting file"""
        mock_check_access.return_value = Mock()
        mock_delete_file.return_value = {"message": "File deleted successfully"}

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.delete("/api/v1/servers/1/files?file_path=test.txt")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "message" in data

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    def test_upload_file_success(self, mock_check_access, client, admin_user):
        """Test uploading file"""
        mock_check_access.return_value = Mock()

        # Create a test file
        test_file = BytesIO(b"test file content")
        test_file.name = "test.txt"

        with patch('app.services.file_management_service.file_management_service.upload_file') as mock_upload:
            mock_upload.return_value = {
                "message": "File uploaded successfully",
                "file": {"name": "test.txt"},
                "extracted_files": []
            }

            with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
                response = client.post(
                    "/api/v1/servers/1/files/upload",
                    files={"file": ("test.txt", test_file, "text/plain")}
                )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "File uploaded successfully"

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.download_file')
    def test_download_file_success(self, mock_download_file, mock_check_access, client, admin_user):
        """Test downloading file"""
        from pathlib import Path
        mock_check_access.return_value = Mock()
        mock_download_file.return_value = (Path("/test/server.properties"), "server.properties")

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('fastapi.responses.FileResponse') as mock_response:
                response = client.get("/api/v1/servers/1/files/download?file_path=server.properties")

        # The endpoint returns a FileResponse, so we check if it was called
        mock_download_file.assert_called_once()

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.create_directory')
    def test_create_directory_success(self, mock_create_dir, mock_check_access, client, admin_user):
        """Test creating directory"""
        mock_check_access.return_value = Mock()
        mock_create_dir.return_value = {
            "message": "Directory created successfully",
            "directory": {"name": "plugins", "type": FileType.directory}
        }

        dir_data = {
            "directory_path": "plugins"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers/1/files/directory", json=dir_data)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["message"] == "Directory created successfully"

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.search_files')
    def test_search_files_success(self, mock_search, mock_check_access, client, admin_user):
        """Test searching files"""
        mock_check_access.return_value = Mock()
        mock_search.return_value = {
            "results": [
                {
                    "file": {"name": "server.properties", "path": "server.properties"},
                    "matches": ["Filename: server.properties"],
                    "match_count": 1
                }
            ],
            "query": "server",
            "total_results": 1,
            "search_time_ms": 50
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/1/files/search?query=server")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_results"] == 1

    def test_file_operations_require_authentication(self, client):
        """Test that file operations require authentication"""
        response = client.get("/api/v1/servers/1/files")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.post("/api/v1/servers/1/files/write", json={"file_path": "test", "content": "test"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_file_access_control(self, client, test_user, admin_user):
        """Test file access control"""
        from fastapi import HTTPException

        # Test that user cannot access other user's server files
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            with patch('app.services.authorization_service.authorization_service.check_server_access') as mock_check:
                mock_check.side_effect = HTTPException(status_code=403, detail="Access denied")
                response = client.get("/api/v1/servers/1/files")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_file_validation_errors(self, client, admin_user):
        """Test file operation validation errors"""
        # Missing file_path for read
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/1/files/read")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Missing content for write
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers/1/files/write", json={"file_path": "test.txt"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Missing directory_path for create directory
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers/1/files/directory", json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_file_search_validation(self, client, admin_user):
        """Test file search validation"""
        # Missing query parameter
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/1/files/search")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Empty query
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/1/files/search?query=")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    def test_file_error_handling(self, mock_check_access, client, admin_user):
        """Test file operation error handling"""
        mock_check_access.return_value = Mock()

        # Test file not found
        with patch('app.services.file_management_service.file_management_service.read_file') as mock_read:
            from fastapi import HTTPException
            mock_read.side_effect = HTTPException(status_code=404, detail="File not found")

            with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
                response = client.get("/api/v1/servers/1/files/read?file_path=nonexistent.txt")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_file_type_filtering(self, client, admin_user):
        """Test file listing with type filtering"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.authorization_service.authorization_service.check_server_access'):
                with patch('app.services.file_management_service.file_management_service.get_server_files') as mock_get:
                    mock_get.return_value = []
                    response = client.get("/api/v1/servers/1/files?file_type=config")

        assert response.status_code == status.HTTP_200_OK
        mock_get.assert_called_once()

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    def test_upload_file_validation(self, mock_check_access, client, admin_user):
        """Test file upload validation"""
        mock_check_access.return_value = Mock()

        # Test upload without file
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers/1/files/upload")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_file_path_validation(self, client, admin_user):
        """Test file path validation and security"""
        # Test path traversal attempt
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.authorization_service.authorization_service.check_server_access'):
                with patch('app.services.file_management_service.file_management_service.read_file') as mock_read:
                    from fastapi import HTTPException
                    mock_read.side_effect = HTTPException(status_code=403, detail="Access denied")
                    response = client.get("/api/v1/servers/1/files/read?file_path=../../../etc/passwd")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    def test_file_search_with_content(self, mock_check_access, client, admin_user):
        """Test file search with content search"""
        mock_check_access.return_value = Mock()

        with patch('app.services.file_management_service.file_management_service.search_files') as mock_search:
            mock_search.return_value = {"results": [], "total_results": 0}

            with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
                response = client.get("/api/v1/servers/1/files/search?query=test&include_content=true&max_results=10")

        assert response.status_code == status.HTTP_200_OK
        mock_search.assert_called_once()

    def test_file_encoding_parameter(self, client, admin_user):
        """Test file operations with encoding parameter"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.authorization_service.authorization_service.check_server_access'):
                with patch('app.services.file_management_service.file_management_service.read_file') as mock_read:
                    mock_read.return_value = "content"
                    response = client.get("/api/v1/servers/1/files/read?file_path=test.txt&encoding=utf-8")

        assert response.status_code == status.HTTP_200_OK