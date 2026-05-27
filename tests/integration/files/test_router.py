from datetime import datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

from app.audit.api.dependencies import get_audit_writer
from app.core.exceptions import (
    FileOperationException,
)
from app.main import app
from app.types import FileType
from tests.helpers.auth import auth_headers_for as get_auth_headers


@pytest.fixture
def mock_audit_writer():
    """Override ``get_audit_writer`` so tests can introspect the
    :class:`AuditEventCommand` instances passed to ``writer.record``
    instead of patching the legacy ``AuditService`` static facade
    (Issue #386 migration).
    """
    writer = MagicMock()
    app.dependency_overrides[get_audit_writer] = lambda: writer
    yield writer
    app.dependency_overrides.pop(get_audit_writer, None)


class TestFileRouter:
    """Test cases for File router endpoints"""

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.get_server_files")
    def test_get_server_files_success(
        self, mock_get_files, mock_check_access, client, admin_user
    ):
        """Test getting server files"""
        mock_files = [
            {
                "name": "server.properties",
                "path": "server.properties",
                "type": FileType.text,
                "is_directory": False,
                "size": 1024,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True},
            },
            {
                "name": "world",
                "path": "world",
                "type": FileType.directory,
                "is_directory": True,
                "size": None,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True},
            },
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

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.get_server_files")
    def test_get_server_files_with_path_filter(
        self, mock_get_files, mock_check_access, client, admin_user
    ):
        """Test getting server files with path filter"""
        mock_get_files.return_value = []
        mock_check_access.return_value = None  # No exception means access granted

        headers = get_auth_headers(admin_user.username)
        response = client.get("/api/v1/files/servers/1/files/world", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        mock_get_files.assert_called_once()

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.get_server_files")
    def test_get_server_files_with_type_filter(
        self, mock_get_files, mock_check_access, client, admin_user
    ):
        """Test getting server files with type filter"""
        mock_get_files.return_value = []
        mock_check_access.return_value = None  # No exception means access granted

        headers = get_auth_headers(admin_user.username)
        response = client.get(
            "/api/v1/files/servers/1/files?file_type=text", headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        mock_get_files.assert_called_once()

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.get_server_files")
    @patch("app.files.application.management.file_management_service.read_file")
    def test_read_file_success(
        self, mock_read_file, mock_get_files, mock_check_access, client, admin_user
    ):
        """Test reading file content"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_read_file.return_value = ("server-port=25565\nmax-players=20", "utf-8")
        mock_get_files.return_value = [
            {
                "name": "server.properties",
                "path": "server.properties",
                "type": FileType.text,
                "is_directory": False,
                "size": 1024,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True},
            }
        ]

        headers = get_auth_headers(admin_user.username)
        response = client.get(
            "/api/v1/files/servers/1/files/server.properties/read", headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "content" in data
        assert data["encoding"] == "utf-8"
        assert "file_info" in data

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.get_server_files")
    @patch("app.files.application.management.file_management_service.read_file")
    def test_read_file_with_encoding(
        self, mock_read_file, mock_get_files, mock_check_access, client, admin_user
    ):
        """Test reading file with custom encoding"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_read_file.return_value = ("content", "latin-1")
        mock_get_files.return_value = [
            {
                "name": "test.txt",
                "path": "test.txt",
                "type": FileType.text,
                "is_directory": False,
                "size": 1024,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True},
            }
        ]

        headers = get_auth_headers(admin_user.username)
        response = client.get(
            "/api/v1/files/servers/1/files/test.txt/read?encoding=latin-1",
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["encoding"] == "latin-1"

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.get_server_files")
    @patch(
        "app.files.application.management.file_management_service.read_image_as_base64"
    )
    def test_read_image_success(
        self, mock_read_image, mock_get_files, mock_check_access, client, admin_user
    ):
        """Test reading image file as base64"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_read_image.return_value = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        mock_get_files.return_value = [
            {
                "name": "test.png",
                "path": "test.png",
                "type": FileType.binary,
                "is_directory": False,
                "size": 1024,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True},
            }
        ]

        headers = get_auth_headers(admin_user.username)
        response = client.get(
            "/api/v1/files/servers/1/files/test.png/read?image=true", headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_image"] is True
        assert data["encoding"] == "base64"
        assert data["image_data"] is not None
        assert data["content"] == ""

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.write_file")
    def test_write_file_success(
        self, mock_write_file, mock_can_modify, mock_check_access, client, admin_user
    ):
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
                "permissions": {"readable": True, "writable": True},
            },
            "backup_created": True,
        }

        write_data = {
            "content": "server-port=25565\nmax-players=30",
            "encoding": "utf-8",
            "create_backup": True,
        }

        headers = get_auth_headers(admin_user.username)
        response = client.put(
            "/api/v1/files/servers/1/files/server.properties",
            json=write_data,
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "File updated successfully"

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    def test_write_file_insufficient_permissions(
        self, mock_can_modify, client, test_user
    ):
        """Test that users without modify permissions cannot write files"""
        mock_can_modify.return_value = False

        write_data = {"content": "test content", "encoding": "utf-8"}

        headers = get_auth_headers(test_user.username)
        response = client.put(
            "/api/v1/files/servers/1/files/test.txt", json=write_data, headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.upload_file")
    def test_upload_file_success(
        self, mock_upload_file, mock_can_modify, mock_check_access, client, admin_user
    ):
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
                "permissions": {"read": True, "write": True, "execute": False},
            },
            "extracted_files": [],
        }

        test_file = BytesIO(b"test file content")
        test_file.name = "test.txt"

        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/upload",
            files={"file": ("test.txt", test_file, "text/plain")},
            data={"destination_path": ""},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "File 'test.txt' uploaded successfully"

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.upload_file")
    def test_upload_file_with_extraction(
        self, mock_upload_file, mock_can_modify, mock_check_access, client, admin_user
    ):
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
                "permissions": {"read": True, "write": True, "execute": False},
            },
            "extracted_files": ["file1.txt", "file2.txt"],
        }

        test_file = BytesIO(b"test archive content")
        test_file.name = "test.zip"

        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/upload",
            files={"file": ("test.zip", test_file, "application/zip")},
            data={"destination_path": "plugins", "extract_if_archive": "true"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    def test_upload_file_insufficient_permissions(
        self, mock_can_modify, client, test_user
    ):
        """Test that users without modify permissions cannot upload files"""
        mock_can_modify.return_value = False

        test_file = BytesIO(b"test content")
        test_file.name = "test.txt"

        headers = get_auth_headers(test_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/upload",
            files={"file": ("test.txt", test_file, "text/plain")},
            headers=headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.download_file")
    def test_download_file_success(
        self, mock_download_file, mock_check_access, client, admin_user
    ):
        """Test downloading file"""
        import tempfile
        from pathlib import Path

        mock_check_access.return_value = None  # No exception means access granted

        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".properties"
        ) as temp_file:
            temp_file.write("server-port=25565\nmax-players=20")
            temp_path = Path(temp_file.name)

        try:
            mock_download_file.return_value = (str(temp_path), "server.properties")

            headers = get_auth_headers(admin_user.username)
            response = client.get(
                "/api/v1/files/servers/1/files/server.properties/download",
                headers=headers,
            )

            mock_download_file.assert_called_once()
            assert response.status_code == 200
        finally:
            # Clean up the temporary file
            if temp_path.exists():
                temp_path.unlink()

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.create_directory")
    def test_create_directory_success(
        self, mock_create_dir, mock_can_modify, mock_check_access, client, admin_user
    ):
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
                "permissions": {"readable": True, "writable": True},
            },
        }

        dir_data = {"name": "plugins"}

        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files//directories", json=dir_data, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "Directory created successfully"

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    def test_create_directory_insufficient_permissions(
        self, mock_can_modify, client, test_user
    ):
        """Test that users without modify permissions cannot create directories"""
        mock_can_modify.return_value = False

        dir_data = {"name": "test_dir"}

        headers = get_auth_headers(test_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files//directories", json=dir_data, headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.delete_file")
    def test_delete_file_success(
        self, mock_delete_file, mock_can_modify, mock_check_access, client, admin_user
    ):
        """Test deleting file"""
        mock_check_access.return_value = None  # No exception means access granted
        mock_can_modify.return_value = True
        mock_delete_file.return_value = {"message": "File deleted successfully"}

        headers = get_auth_headers(admin_user.username)
        response = client.delete(
            "/api/v1/files/servers/1/files/test.txt", headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "message" in data

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    def test_delete_file_insufficient_permissions(
        self, mock_can_modify, client, test_user
    ):
        """Test that users without modify permissions cannot delete files"""
        mock_can_modify.return_value = False

        headers = get_auth_headers(test_user.username)
        response = client.delete(
            "/api/v1/files/servers/1/files/test.txt", headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.search_files")
    def test_search_files_success(
        self, mock_search, mock_check_access, client, admin_user
    ):
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
                        "permissions": {"readable": True, "writable": True},
                    },
                    "matches": ["Filename: server.properties"],
                    "match_count": 1,
                }
            ],
            "query": "server",
            "total_results": 1,
            "search_time_ms": 50,
        }

        search_data = {
            "query": "server",
            "file_type": None,
            "include_content": False,
            "max_results": 100,
        }

        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/search", json=search_data, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_results"] == 1
        assert len(data["results"]) == 1

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.search_files")
    def test_search_files_with_content(
        self, mock_search, mock_check_access, client, admin_user
    ):
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
                        "permissions": {"readable": True, "writable": True},
                    },
                    "matches": ["Content match: server-port=25565"],
                    "match_count": 1,
                }
            ],
            "query": "25565",
            "total_results": 1,
            "search_time_ms": 100,
        }

        search_data = {
            "query": "25565",
            "file_type": FileType.text,
            "include_content": True,
            "max_results": 50,
        }

        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/search", json=search_data, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_results"] == 1

    def test_file_operations_require_authentication(self, client):
        """Test that file operations require authentication"""
        response = client.get("/api/v1/files/servers/1/files")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.put(
            "/api/v1/files/servers/1/files/test.txt", json={"content": "test"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.post("/api/v1/files/servers/1/files/upload")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.delete("/api/v1/files/servers/1/files/test.txt")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.post("/api/v1/files/servers/1/files/test/directories")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    def test_file_read_validation_errors(self, mock_check_access, client, admin_user):
        """Test file read validation errors"""
        mock_check_access.return_value = None  # No exception means access granted
        # Test accessing files endpoint without /read suffix - should return file list, not read content
        headers = get_auth_headers(admin_user.username)
        response = client.get(
            "/api/v1/files/servers/1/files/nonexistent_file_path/read", headers=headers
        )
        # This should either return 404 or some other error, not 422
        assert response.status_code in [
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]

    def test_file_write_validation_errors(self, client, admin_user):
        """Test file write validation errors"""
        # Missing content in request body
        headers = get_auth_headers(admin_user.username)
        response = client.put(
            "/api/v1/files/servers/1/files/test.txt", json={}, headers=headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_file_search_validation_errors(self, client, admin_user):
        """Test file search validation errors"""
        # Empty request body
        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/search", json={}, headers=headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_directory_create_validation_errors(self, client, admin_user):
        """Test directory create validation errors"""
        # Missing name field
        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/test/directories", json={}, headers=headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.files.application.management.file_management_service.read_file")
    def test_file_error_handling(
        self, mock_read_file, mock_check_access, client, admin_user
    ):
        """Test file operation error handling"""
        mock_check_access.return_value = None  # No exception means access granted
        # Test file not found
        mock_read_file.side_effect = HTTPException(
            status_code=404, detail="File not found"
        )

        headers = get_auth_headers(admin_user.username)
        response = client.get(
            "/api/v1/files/servers/1/files/nonexistent.txt/read", headers=headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_upload_file_without_file(self, client, admin_user):
        """Test file upload without providing a file"""
        headers = get_auth_headers(admin_user.username)
        response = client.post("/api/v1/files/servers/1/files/upload", headers=headers)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestFileRenameRouter:
    """Test cases for File rename router endpoint"""

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.rename_file")
    def test_rename_file_success(
        self, mock_rename_file, mock_can_modify, client, admin_user
    ):
        """Test successful file rename"""
        mock_can_modify.return_value = True
        mock_rename_file.return_value = {
            "message": "Successfully renamed 'test.txt' to 'renamed.txt'",
            "old_path": "test.txt",
            "new_path": "renamed.txt",
            "file": {
                "name": "renamed.txt",
                "path": "renamed.txt",
                "type": FileType.text,
                "is_directory": False,
                "size": 1024,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True},
            },
        }

        rename_data = {"new_name": "renamed.txt"}

        headers = get_auth_headers(admin_user.username)
        response = client.patch(
            "/api/v1/files/servers/1/files/test.txt/rename",
            json=rename_data,
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "Successfully renamed 'test.txt' to 'renamed.txt'"
        assert data["old_path"] == "test.txt"
        assert data["new_path"] == "renamed.txt"
        assert data["file"]["name"] == "renamed.txt"

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.rename_file")
    def test_rename_directory_success(
        self, mock_rename_file, mock_can_modify, client, admin_user
    ):
        """Test successful directory rename"""
        mock_can_modify.return_value = True
        mock_rename_file.return_value = {
            "message": "Successfully renamed 'old_folder' to 'new_folder'",
            "old_path": "old_folder",
            "new_path": "new_folder",
            "file": {
                "name": "new_folder",
                "path": "new_folder",
                "type": FileType.directory,
                "is_directory": True,
                "size": None,
                "modified": datetime.now(),
                "permissions": {"readable": True, "writable": True},
            },
        }

        rename_data = {"new_name": "new_folder"}

        headers = get_auth_headers(admin_user.username)
        response = client.patch(
            "/api/v1/files/servers/1/files/old_folder/rename",
            json=rename_data,
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "Successfully renamed 'old_folder' to 'new_folder'"
        assert data["file"]["is_directory"] is True

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    def test_rename_file_insufficient_permissions(
        self, mock_can_modify, client, test_user
    ):
        """Test that users without modify permissions cannot rename files"""
        mock_can_modify.return_value = False

        rename_data = {"new_name": "renamed.txt"}

        headers = get_auth_headers(test_user.username)
        response = client.patch(
            "/api/v1/files/servers/1/files/test.txt/rename",
            json=rename_data,
            headers=headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.rename_file")
    def test_rename_file_invalid_filename(
        self, mock_rename_file, mock_can_modify, client, admin_user
    ):
        """Test rename with invalid filename"""
        mock_can_modify.return_value = True

        from app.core.exceptions import InvalidRequestException

        mock_rename_file.side_effect = InvalidRequestException(
            "Invalid filename: contains illegal characters"
        )

        rename_data = {"new_name": "invalid<>filename.txt"}

        headers = get_auth_headers(admin_user.username)
        response = client.patch(
            "/api/v1/files/servers/1/files/test.txt/rename",
            json=rename_data,
            headers=headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.rename_file")
    def test_rename_file_already_exists(
        self, mock_rename_file, mock_can_modify, client, admin_user
    ):
        """Test rename when target file already exists"""
        mock_can_modify.return_value = True

        mock_rename_file.side_effect = FileOperationException(
            "rename", "test.txt", "File or directory 'existing.txt' already exists"
        )

        rename_data = {"new_name": "existing.txt"}

        headers = get_auth_headers(admin_user.username)
        response = client.patch(
            "/api/v1/files/servers/1/files/test.txt/rename",
            json=rename_data,
            headers=headers,
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.rename_file")
    def test_rename_file_not_found(
        self, mock_rename_file, mock_can_modify, client, admin_user
    ):
        """Test rename when source file doesn't exist"""
        mock_can_modify.return_value = True

        mock_rename_file.side_effect = FileOperationException(
            "access", "nonexistent.txt", "Path not found"
        )

        rename_data = {"new_name": "renamed.txt"}

        headers = get_auth_headers(admin_user.username)
        response = client.patch(
            "/api/v1/files/servers/1/files/nonexistent.txt/rename",
            json=rename_data,
            headers=headers,
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_rename_file_validation_errors(self, client, admin_user):
        """Test rename validation errors"""
        # Missing new_name in request body
        headers = get_auth_headers(admin_user.username)
        response = client.patch(
            "/api/v1/files/servers/1/files/test.txt/rename", json={}, headers=headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Empty new_name
        response = client.patch(
            "/api/v1/files/servers/1/files/test.txt/rename",
            json={"new_name": ""},
            headers=headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # new_name too long (over 255 characters)
        long_name = "a" * 256
        response = client.patch(
            "/api/v1/files/servers/1/files/test.txt/rename",
            json={"new_name": long_name},
            headers=headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_rename_file_requires_authentication(self, client):
        """Test that rename operations require authentication"""
        response = client.patch(
            "/api/v1/files/servers/1/files/test.txt/rename",
            json={"new_name": "renamed.txt"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Issue #36 Phase 1 + Issue #35: audit wiring and structured error envelope
# ---------------------------------------------------------------------------


class TestFileRouterAuditWiring:
    """Verify the file router emits audit events for both success and
    failure paths on the mutating endpoints (#36 Phase 1), and that
    file-domain exceptions surface through the global error handlers
    with the standard envelope (#35).

    Issue #386: the router now records events via an injected
    :class:`~app.audit.domain.ports.AuditWriter` rather than calling
    the static ``AuditService`` facade. Tests override
    ``get_audit_writer`` with a ``MagicMock`` and assert against the
    :class:`AuditEventCommand` instance passed to ``writer.record``.
    """

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.write_file")
    def test_write_file_emits_audit_event_on_success(
        self,
        mock_write_file,
        mock_can_modify,
        mock_check_access,
        mock_audit_writer,
        client,
        admin_user,
    ):
        mock_check_access.return_value = None
        mock_can_modify.return_value = True
        mock_write_file.return_value = {
            "message": "File updated successfully",
            "file": {
                "name": "server.properties",
                "path": "server.properties",
                "type": FileType.text,
                "is_directory": False,
                "size": 5,
                "modified": datetime.now(),
                "permissions": {"read": True, "write": True, "execute": False},
            },
            "backup_created": True,
        }

        headers = get_auth_headers(admin_user.username)
        response = client.put(
            "/api/v1/files/servers/1/files/server.properties",
            json={"content": "hello", "encoding": "utf-8", "create_backup": True},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        mock_audit_writer.record.assert_called_once()
        command = mock_audit_writer.record.call_args.args[0]
        assert command.action == "file_write"
        assert command.resource_type == "file"
        assert command.resource_id == 1
        assert command.details["server_id"] == 1
        assert command.details["file_path"] == "server.properties"
        assert command.details["encoding"] == "utf-8"
        assert command.details["backup_created"] is True
        assert command.details["bytes"] == 5
        assert "duration_ms" in command.details

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.write_file")
    def test_write_file_emits_failure_audit_on_error(
        self,
        mock_write_file,
        mock_can_modify,
        mock_check_access,
        mock_audit_writer,
        client,
        admin_user,
    ):
        from app.core.exceptions import FileMissingError

        mock_check_access.return_value = None
        mock_can_modify.return_value = True
        mock_write_file.side_effect = FileMissingError("write", "server.properties")

        headers = get_auth_headers(admin_user.username)
        response = client.put(
            "/api/v1/files/servers/1/files/server.properties",
            json={"content": "hi", "encoding": "utf-8", "create_backup": False},
            headers=headers,
        )

        # File-domain exception maps to 404 with structured envelope
        assert response.status_code == status.HTTP_404_NOT_FOUND
        body = response.json()
        assert body["error"] == "FILE_NOT_FOUND"
        assert body["status_code"] == 404
        assert "request_id" in body
        # ``details`` carries the structured ``extra_details`` payload
        codes = {d["code"] for d in (body.get("details") or [])}
        assert "FILE_PATH" in codes
        assert "SUGGESTED_ACTION" in codes

        # Failure audit event was emitted with error_type
        mock_audit_writer.record.assert_called_once()
        command = mock_audit_writer.record.call_args.args[0]
        assert command.action == "file_write_failure"
        assert command.details["error_type"] == "FileMissingError"

    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.delete_file")
    def test_delete_file_emits_audit_event_on_success(
        self,
        mock_delete_file,
        mock_can_modify,
        mock_audit_writer,
        client,
        admin_user,
    ):
        mock_can_modify.return_value = True
        mock_delete_file.return_value = {"message": "File 'foo' deleted successfully"}

        headers = get_auth_headers(admin_user.username)
        response = client.delete(
            "/api/v1/files/servers/1/files/foo",
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        mock_audit_writer.record.assert_called_once()
        command = mock_audit_writer.record.call_args.args[0]
        assert command.action == "file_delete"

    def test_write_request_size_limit_returns_422(self, client, admin_user):
        """``FileWriteRequest.content`` carries a 50 MiB cap (Issue #35).

        The router rejects oversized payloads at validation time before
        the audit hook runs.
        """
        from app.files.schemas import MAX_FILE_WRITE_BYTES

        oversized = "a" * (MAX_FILE_WRITE_BYTES + 1)
        headers = get_auth_headers(admin_user.username)
        response = client.put(
            "/api/v1/files/servers/1/files/foo.txt",
            json={"content": oversized, "encoding": "utf-8", "create_backup": False},
            headers=headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestIssue341FileRouterContract:
    """Issue #341: enforce upload size, encoding validation, and rename 409s
    end-to-end through the FastAPI router.
    """

    def test_write_invalid_encoding_returns_422_envelope(
        self, mock_audit_writer, client, admin_user
    ):
        """Unknown encodings are rejected at validation time (#341).

        Pre-fix the router raised ``LookupError`` from
        ``str.encode(payload.encoding, ...)`` *before* ``_safe_audit``
        was wired up, leaking a 500 with no envelope. The
        ``@field_validator`` on :class:`FileWriteRequest.encoding` turns
        the same input into a clean 422 with the standard ``details``
        payload, and the failure audit is skipped because the request
        never reaches the handler body.
        """
        headers = get_auth_headers(admin_user.username)
        response = client.put(
            "/api/v1/files/servers/1/files/server.properties",
            json={
                "content": "hi",
                "encoding": "definitely-not-a-codec",
                "create_backup": False,
            },
            headers=headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        body = response.json()
        assert body["error"] == "VALIDATION_ERROR"
        # Validation rejection short-circuits the handler so no audit fires.
        mock_audit_writer.record.assert_not_called()

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.upload_file")
    def test_upload_too_large_returns_413_envelope(
        self,
        mock_upload_file,
        mock_can_modify,
        mock_check_access,
        client,
        admin_user,
    ):
        """``FileTooLargeError`` from the service surfaces as a 413
        with ``FILE_TOO_LARGE`` + size metadata in the envelope.
        """
        from app.core.exceptions import FileTooLargeError

        mock_check_access.return_value = None
        mock_can_modify.return_value = True
        mock_upload_file.side_effect = FileTooLargeError(
            "upload",
            "huge.bin",
            size_bytes=200_000_000,
            max_bytes=100 * 1024 * 1024,
        )

        test_file = BytesIO(b"payload")
        test_file.name = "huge.bin"

        headers = get_auth_headers(admin_user.username)
        response = client.post(
            "/api/v1/files/servers/1/files/upload",
            files={"file": ("huge.bin", test_file, "application/octet-stream")},
            data={"destination_path": ""},
            headers=headers,
        )

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        body = response.json()
        assert body["error"] == "FILE_TOO_LARGE"
        codes = {d["code"]: d["message"] for d in body.get("details") or []}
        assert codes.get("FILE_SIZE_BYTES") == "200000000"
        assert codes.get("FILE_MAX_BYTES") == str(100 * 1024 * 1024)

    @patch(
        "app.servers.application.authorization.AuthorizationService.check_server_access",
        new_callable=AsyncMock,
    )
    @patch("app.servers.application.authorization.AuthorizationService.can_modify_files")
    @patch("app.files.application.management.file_management_service.rename_file")
    def test_rename_destination_exists_returns_409_envelope(
        self,
        mock_rename_file,
        mock_can_modify,
        mock_check_access,
        client,
        admin_user,
    ):
        """Rename onto an existing path surfaces as ``FILE_ALREADY_EXISTS`` 409."""
        from app.core.exceptions import FileAlreadyExistsError

        mock_check_access.return_value = None
        mock_can_modify.return_value = True
        mock_rename_file.side_effect = FileAlreadyExistsError(
            "rename",
            "/srv/src.txt",
            existing_path="dst.txt",
        )

        headers = get_auth_headers(admin_user.username)
        response = client.patch(
            "/api/v1/files/servers/1/files/src.txt/rename",
            json={"new_name": "dst.txt"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        body = response.json()
        assert body["error"] == "FILE_ALREADY_EXISTS"
        # The existing path is round-tripped to the client so the UI can
        # suggest a resolution without an extra round-trip.
        details = {d["code"]: d["message"] for d in body.get("details") or []}
        assert details.get("EXISTING_PATH") == "dst.txt"
        assert any(
            "different destination" in d["message"]
            for d in body.get("details") or []
            if d.get("code") == "SUGGESTED_ACTION"
        )
