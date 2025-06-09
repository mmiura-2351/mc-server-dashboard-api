from datetime import datetime
from io import BytesIO
from unittest.mock import patch

from fastapi import HTTPException, status

from app.auth.auth import create_access_token
from app.types import FileType
from app.core.exceptions import (
    ServerNotFoundException,
    FileOperationException,
    AccessDeniedException
)


def get_auth_headers(username: str):
    """認証ヘッダーを生成"""
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


class TestFileRouter:
    """Test cases for File router endpoints"""

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.get_server_files')
    def test_get_server_files_success(self, mock_get_files, mock_check_access, client, admin_user):
        """Test getting server files"""
        mock_files = [
            {
                "name": "server.properties",
                "path": "server.properties",
                "type": FileType.text,
                "is_directory": False,
                "size": 1024,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True}
            },
            {
                "name": "world",
                "path": "world",
                "type": FileType.directory,
                "is_directory": True,
                "size": None,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True}
            }
        ]
        mock_get_files.return_value = mock_files
        mock_check_access.return_value = None  # No exception means access granted

        headers = get_auth_headers(admin_user.username)
        response = client.get("/api/v1/files/servers/1/files", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "files" in data
        assert len(data["files"]) == 2
        assert data["current_path"] == ""
        assert data["total_files"] == 2

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.get_server_files')
    def test_get_server_files_with_path_filter(self, mock_get_files, mock_check_access, client, admin_user):
        """Test getting server files with path filter"""
        mock_get_files.return_value = []
        mock_check_access.return_value = None  # No exception means access granted

        headers = get_auth_headers(admin_user.username)
        response = client.get("/api/v1/files/servers/1/files/world", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        mock_get_files.assert_called_once()

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.get_server_files')
    def test_get_server_files_with_type_filter(self, mock_get_files, mock_check_access, client, admin_user):
        """Test getting server files with type filter"""
        mock_get_files.return_value = []
        mock_check_access.return_value = None  # No exception means access granted

        headers = get_auth_headers(admin_user.username)
        response = client.get("/api/v1/files/servers/1/files?file_type=text", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        mock_get_files.assert_called_once()

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.get_server_files')
    @patch('app.services.file_management_service.file_management_service.read_file')
    def test_read_file_success(self, mock_read_file, mock_get_files, mock_check_access, client, admin_user):
        """Test reading file content"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_read_file.return_value = "server-port=25565\nmax-players=20"
        mock_get_files.return_value = [{
            "name": "server.properties",
            "path": "server.properties",
            "type": FileType.text,
            "is_directory": False,
            "size": 1024,
            "modified": datetime.now(),
            "permissions": {"readable": True, "writable": True}
        }]

        headers = get_auth_headers(admin_user.username)
        response = client.get("/api/v1/files/servers/1/files/server.properties/read", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "content" in data
        assert data["encoding"] == "utf-8"
        assert "file_info" in data

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.get_server_files')
    @patch('app.services.file_management_service.file_management_service.read_file')
    def test_read_file_with_encoding(self, mock_read_file, mock_get_files, mock_check_access, client, admin_user):
        """Test reading file with custom encoding"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_read_file.return_value = "content"
        mock_get_files.return_value = [{
            "name": "test.txt",
            "path": "test.txt",
            "type": FileType.text,
            "is_directory": False,
            "size": 1024,
            "modified": datetime.now(),
            "permissions": {"readable": True, "writable": True}
        }]

        headers = get_auth_headers(admin_user.username)
        response = client.get("/api/v1/files/servers/1/files/test.txt/read?encoding=latin-1", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["encoding"] == "latin-1"

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.get_server_files')
    @patch('app.services.file_management_service.file_management_service.read_image_as_base64')
    def test_read_image_success(self, mock_read_image, mock_get_files, mock_check_access, client, admin_user):
        """Test reading image file as base64"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_read_image.return_value = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        mock_get_files.return_value = [{
            "name": "test.png",
            "path": "test.png",
            "type": FileType.binary,
            "is_directory": False,
            "size": 1024,
            "modified": datetime.now(),
            "permissions": {"readable": True, "writable": True}
        }]

        headers = get_auth_headers(admin_user.username)
        response = client.get("/api/v1/files/servers/1/files/test.png/read?image=true", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_image"] is True
        assert data["encoding"] == "base64"
        assert data["image_data"] is not None
        assert data["content"] == ""

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.authorization_service.authorization_service.can_modify_files')
    @patch('app.services.file_management_service.file_management_service.write_file')
    def test_write_file_success(self, mock_write_file, mock_can_modify, mock_check_access, client, admin_user):
        """Test writing file content"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_can_modify.return_value = True
        mock_write_file.return_value = {
            "message": "File updated successfully",
            "file": {
                "name": "server.properties",
                "path": "server.properties",
                "type": FileType.text,
                "is_directory": False,
                "size": 1024,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True}
            },
            "backup_created": True
        }

        write_data = {
            "content": "server-port=25565\nmax-players=30",
            "encoding": "utf-8",
            "create_backup": True
        }

        headers = get_auth_headers(admin_user.username)
        response = client.put("/api/v1/files/servers/1/files/server.properties", json=write_data, headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "File updated successfully"

    @patch('app.services.authorization_service.authorization_service.can_modify_files')
    def test_write_file_insufficient_permissions(self, mock_can_modify, client, test_user):
        """Test that users without modify permissions cannot write files"""
        mock_can_modify.return_value = False

        write_data = {
            "content": "test content",
            "encoding": "utf-8"
        }

        headers = get_auth_headers(test_user.username)
        response = client.put("/api/v1/files/servers/1/files/test.txt", json=write_data, headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.authorization_service.authorization_service.can_modify_files')
    @patch('app.services.file_management_service.file_management_service.upload_file')
    def test_upload_file_success(self, mock_upload_file, mock_can_modify, mock_check_access, client, admin_user):
        """Test uploading file"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_can_modify.return_value = True
        mock_upload_file.return_value = {
            "message": "File 'test.txt' uploaded successfully",
            "file": {
                "name": "test.txt",
                "path": "test.txt",
                "type": FileType.text,
                "is_directory": False,
                "size": 1024,
                "modified": datetime.now(),
                "permissions": {"read": True, "write": True, "execute": False}
            },
            "extracted_files": []
        }

        test_file = BytesIO(b"test file content")
        test_file.name = "test.txt"

        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/upload",
            files={"file": ("test.txt", test_file, "text/plain")},
            data={"destination_path": ""},
            headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "File 'test.txt' uploaded successfully"

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.authorization_service.authorization_service.can_modify_files')
    @patch('app.services.file_management_service.file_management_service.upload_file')
    def test_upload_file_with_extraction(self, mock_upload_file, mock_can_modify, mock_check_access, client, admin_user):
        """Test uploading file with archive extraction"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_can_modify.return_value = True
        mock_upload_file.return_value = {
            "message": "Archive 'test.zip' uploaded and extracted successfully",
            "file": {
                "name": "test.zip",
                "path": "test.zip",
                "type": FileType.binary,
                "is_directory": False,
                "size": 2048,
                "modified": datetime.now(),
                "permissions": {"read": True, "write": True, "execute": False}
            },
            "extracted_files": ["file1.txt", "file2.txt"]
        }

        test_file = BytesIO(b"test archive content")
        test_file.name = "test.zip"

        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/upload",
            files={"file": ("test.zip", test_file, "application/zip")},
            data={"destination_path": "plugins", "extract_if_archive": "true"},
            headers=headers
        )

        assert response.status_code == status.HTTP_200_OK

    @patch('app.services.authorization_service.authorization_service.can_modify_files')
    def test_upload_file_insufficient_permissions(self, mock_can_modify, client, test_user):
        """Test that users without modify permissions cannot upload files"""
        mock_can_modify.return_value = False

        test_file = BytesIO(b"test content")
        test_file.name = "test.txt"

        headers = get_auth_headers(test_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/upload",
            files={"file": ("test.txt", test_file, "text/plain")},
            headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.download_file')
    def test_download_file_success(self, mock_download_file, mock_check_access, client, admin_user):
        """Test downloading file"""
        import tempfile
        from pathlib import Path
        
        mock_check_access.return_value = None  # No exception means access granted
        
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.properties') as temp_file:
            temp_file.write("server-port=25565\nmax-players=20")
            temp_path = Path(temp_file.name)
        
        try:
            mock_download_file.return_value = (str(temp_path), "server.properties")

            headers = get_auth_headers(admin_user.username)
            response = client.get("/api/v1/files/servers/1/files/server.properties/download", headers=headers)

            mock_download_file.assert_called_once()
            assert response.status_code == 200
        finally:
            # Clean up the temporary file
            if temp_path.exists():
                temp_path.unlink()

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.authorization_service.authorization_service.can_modify_files')
    @patch('app.services.file_management_service.file_management_service.create_directory')
    def test_create_directory_success(self, mock_create_dir, mock_can_modify, mock_check_access, client, admin_user):
        """Test creating directory"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_can_modify.return_value = True
        mock_create_dir.return_value = {
            "message": "Directory created successfully",
            "directory": {
                "name": "plugins",
                "path": "plugins",
                "type": FileType.directory,
                "is_directory": True,
                "size": None,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True}
            }
        }

        dir_data = {
            "name": "plugins"
        }

        headers = get_auth_headers(admin_user.username)
        response = client.post("/api/v1/files/servers/1/files//directories", json=dir_data, headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "Directory created successfully"

    @patch('app.services.authorization_service.authorization_service.can_modify_files')
    def test_create_directory_insufficient_permissions(self, mock_can_modify, client, test_user):
        """Test that users without modify permissions cannot create directories"""
        mock_can_modify.return_value = False

        dir_data = {
            "name": "test_dir"
        }

        headers = get_auth_headers(test_user.username)
        response = client.post("/api/v1/files/servers/1/files//directories", json=dir_data, headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.authorization_service.authorization_service.can_modify_files')
    @patch('app.services.file_management_service.file_management_service.delete_file')
    def test_delete_file_success(self, mock_delete_file, mock_can_modify, mock_check_access, client, admin_user):
        """Test deleting file"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_can_modify.return_value = True
        mock_delete_file.return_value = {"message": "File deleted successfully"}

        headers = get_auth_headers(admin_user.username)
        response = client.delete("/api/v1/files/servers/1/files/test.txt", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "message" in data

    @patch('app.services.authorization_service.authorization_service.can_modify_files')
    def test_delete_file_insufficient_permissions(self, mock_can_modify, client, test_user):
        """Test that users without modify permissions cannot delete files"""
        mock_can_modify.return_value = False

        headers = get_auth_headers(test_user.username)
        response = client.delete("/api/v1/files/servers/1/files/test.txt", headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.search_files')
    def test_search_files_success(self, mock_search, mock_check_access, client, admin_user):
        """Test searching files"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_search.return_value = {
            "results": [
                {
                    "file": {
                        "name": "server.properties", 
                        "path": "server.properties",
                        "type": FileType.text,
                        "is_directory": False,
                        "size": 1024,
                        "modified": datetime.now(),
                        "permissions": {"readable": True, "writable": True}
                    },
                    "matches": ["Filename: server.properties"],
                    "match_count": 1
                }
            ],
            "query": "server",
            "total_results": 1,
            "search_time_ms": 50
        }

        search_data = {
            "query": "server",
            "file_type": None,
            "include_content": False,
            "max_results": 100
        }

        headers = get_auth_headers(admin_user.username)
        response = client.post("/api/v1/files/servers/1/files/search", json=search_data, headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_results"] == 1
        assert len(data["results"]) == 1

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.search_files')
    def test_search_files_with_content(self, mock_search, mock_check_access, client, admin_user):
        """Test searching files with content search"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_search.return_value = {
            "results": [
                {
                    "file": {
                        "name": "config.yml", 
                        "path": "config.yml",
                        "type": FileType.text,
                        "is_directory": False,
                        "size": 512,
                        "modified": datetime.now(),
                        "permissions": {"readable": True, "writable": True}
                    },
                    "matches": ["Content match: server-port=25565"],
                    "match_count": 1
                }
            ],
            "query": "25565",
            "total_results": 1,
            "search_time_ms": 100
        }

        search_data = {
            "query": "25565",
            "file_type": FileType.text,
            "include_content": True,
            "max_results": 50
        }

        headers = get_auth_headers(admin_user.username)
        response = client.post("/api/v1/files/servers/1/files/search", json=search_data, headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_results"] == 1

    def test_file_operations_require_authentication(self, client):
        """Test that file operations require authentication"""
        response = client.get("/api/v1/files/servers/1/files")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.put("/api/v1/files/servers/1/files/test.txt", json={"content": "test"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.post("/api/v1/files/servers/1/files/upload")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.delete("/api/v1/files/servers/1/files/test.txt")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.post("/api/v1/files/servers/1/files/test/directories")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    def test_file_read_validation_errors(self, mock_check_access, client, admin_user):
        """Test file read validation errors"""
        mock_check_access.return_value = None  # No exception means access granted
        # Test accessing files endpoint without /read suffix - should return file list, not read content
        headers = get_auth_headers(admin_user.username)
        response = client.get("/api/v1/files/servers/1/files/nonexistent_file_path/read", headers=headers)
        # This should either return 404 or some other error, not 422
        assert response.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_500_INTERNAL_SERVER_ERROR]

    def test_file_write_validation_errors(self, client, admin_user):
        """Test file write validation errors"""
        # Missing content in request body
        headers = get_auth_headers(admin_user.username)
        response = client.put("/api/v1/files/servers/1/files/test.txt", json={}, headers=headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_file_search_validation_errors(self, client, admin_user):
        """Test file search validation errors"""
        # Empty request body
        headers = get_auth_headers(admin_user.username)
        response = client.post("/api/v1/files/servers/1/files/search", json={}, headers=headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_directory_create_validation_errors(self, client, admin_user):
        """Test directory create validation errors"""
        # Missing name field
        headers = get_auth_headers(admin_user.username)
        response = client.post("/api/v1/files/servers/1/files/test/directories", json={}, headers=headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.file_management_service.file_management_service.read_file')
    def test_file_error_handling(self, mock_read_file, mock_check_access, client, admin_user):
        """Test file operation error handling"""
        mock_check_access.return_value = None  # No exception means access granted
        # Test file not found
        mock_read_file.side_effect = HTTPException(status_code=404, detail="File not found")

        headers = get_auth_headers(admin_user.username)
        response = client.get("/api/v1/files/servers/1/files/nonexistent.txt/read", headers=headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_upload_file_without_file(self, client, admin_user):
        """Test file upload without providing a file"""
        headers = get_auth_headers(admin_user.username)
        response = client.post("/api/v1/files/servers/1/files/upload", headers=headers)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY