"""Security tests for path traversal and file operation vulnerabilities.

This test module validates that all security fixes prevent path traversal attacks
and other file operation vulnerabilities.
"""

import io
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from app.core.security import (
    FileOperationValidator,
    PathValidator,
    SecurityError,
    TarExtractor,
)
from app.servers.models import ServerType
from app.servers.schemas import ServerCreateRequest
from app.servers.service import ServerFileSystemService, ServerValidationService
from app.services.backup_service import BackupFileService


class TestPathValidator:
    """Test path validation utilities."""

    def test_validate_safe_name_valid_names(self):
        """Test that valid names pass validation."""
        valid_names = [
            "test-server",
            "my_server",
            "server123",
            "My-Server_123",
            "simple",
        ]
        
        for name in valid_names:
            result = PathValidator.validate_safe_name(name)
            assert result == name

    def test_validate_safe_name_invalid_characters(self):
        """Test that names with invalid characters are rejected."""
        invalid_names = [
            "../../../etc/passwd",
            "server/with/slashes",
            "server\\with\\backslashes", 
            "server with spaces",
            "server@domain",
            "server#hash",
            "server$dollar",
            "server%percent",
            "server&ampersand",
            "server*asterisk",
            "server(paren)",
            "server[bracket]",
            "server{brace}",
            "server|pipe",
            "server;semicolon",
            "server:colon",
            "server'quote",
            'server"doublequote',
            "server<less>",
            "server?question",
            "server+plus",
            "server=equal",
        ]
        
        for name in invalid_names:
            with pytest.raises(SecurityError, match="invalid characters"):
                PathValidator.validate_safe_name(name)

    def test_validate_safe_name_path_traversal(self):
        """Test that path traversal patterns are rejected."""
        traversal_names = [
            "..",
            "../etc",
            "normal/../etc",
            "server..etc",
            "..server",
            "server..",
        ]
        
        for name in traversal_names:
            with pytest.raises(SecurityError):
                PathValidator.validate_safe_name(name)

    def test_validate_safe_name_reserved_names(self):
        """Test that reserved names are rejected."""
        reserved_names = [
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "LPT1", "LPT2",
            "con", "prn", "aux", "nul",  # Test case insensitive
        ]
        
        for name in reserved_names:
            with pytest.raises(SecurityError, match="reserved name"):
                PathValidator.validate_safe_name(name)

    def test_validate_safe_name_length_limit(self):
        """Test that overly long names are rejected."""
        long_name = "a" * 300
        with pytest.raises(SecurityError, match="too long"):
            PathValidator.validate_safe_name(long_name, max_length=255)

    def test_validate_safe_name_empty_or_none(self):
        """Test that empty or None names are rejected."""
        with pytest.raises(SecurityError, match="non-empty string"):
            PathValidator.validate_safe_name("")
        
        with pytest.raises(SecurityError, match="non-empty string"):
            PathValidator.validate_safe_name(None)

    def test_validate_safe_path_within_base(self):
        """Test that paths within base directory are allowed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            safe_path = base_dir / "subdir" / "file.txt"
            
            # Create the path to test
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            safe_path.touch()
            
            result = PathValidator.validate_safe_path(safe_path, base_dir)
            assert result.is_absolute()
            assert str(result).startswith(str(base_dir.resolve()))

    def test_validate_safe_path_traversal_attempt(self):
        """Test that path traversal attempts are blocked."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir) / "servers"
            base_dir.mkdir()
            
            # Try to traverse outside base directory
            malicious_path = base_dir / ".." / ".." / "etc" / "passwd"
            
            with pytest.raises(SecurityError, match="Path traversal attempt"):
                PathValidator.validate_safe_path(malicious_path, base_dir)

    def test_create_safe_server_directory(self):
        """Test safe server directory creation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            
            # Test valid server name
            server_dir = PathValidator.create_safe_server_directory("test-server", base_dir)
            assert server_dir == base_dir / "test-server"

    def test_create_safe_server_directory_invalid_name(self):
        """Test that invalid server names are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            
            with pytest.raises(SecurityError):
                PathValidator.create_safe_server_directory("../../../etc", base_dir)


class TestTarExtractor:
    """Test secure tar extraction utilities."""

    def create_malicious_tar(self, temp_dir: Path) -> Path:
        """Create a tar file with malicious paths for testing."""
        tar_path = temp_dir / "malicious.tar.gz"
        
        with tarfile.open(tar_path, "w:gz") as tar:
            # Add a safe file
            safe_info = tarfile.TarInfo("safe_file.txt")
            safe_info.size = 5
            tar.addfile(safe_info, io.BytesIO(b"safe\n"))
            
            # Add a malicious file with path traversal
            malicious_info = tarfile.TarInfo("../../../etc/passwd")
            malicious_info.size = 7
            tar.addfile(malicious_info, io.BytesIO(b"hacked\n"))
        
        return tar_path

    def test_validate_tar_member_safe_file(self):
        """Test that safe tar members pass validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            
            # Create a safe tar member
            member = tarfile.TarInfo("safe_file.txt")
            member.size = 5
            
            # Should not raise an exception
            TarExtractor.validate_tar_member(member, target_dir)

    def test_validate_tar_member_path_traversal(self):
        """Test that tar members with path traversal are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            
            # Test various path traversal patterns
            malicious_names = [
                "../../../etc/passwd",
                "/etc/passwd",
                "..\\..\\..\\windows\\system32",
                "normal/../../../etc/hosts",
            ]
            
            for name in malicious_names:
                member = tarfile.TarInfo(name)
                member.size = 5
                
                with pytest.raises(SecurityError):
                    TarExtractor.validate_tar_member(member, target_dir)

    def test_validate_tar_member_symlinks(self):
        """Test that symbolic links are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            
            # Create a symbolic link tar member
            member = tarfile.TarInfo("symlink")
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
            
            with pytest.raises(SecurityError, match="symbolic"):
                TarExtractor.validate_tar_member(member, target_dir)

    def test_validate_tar_member_device_files(self):
        """Test that device files are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            
            # Create a device file tar member
            member = tarfile.TarInfo("device")
            member.type = tarfile.CHRTYPE
            
            with pytest.raises(SecurityError, match="device file"):
                TarExtractor.validate_tar_member(member, target_dir)

    def test_safe_extract_tar_malicious_archive(self):
        """Test that malicious tar archives are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            target_dir = temp_path / "extract"
            target_dir.mkdir()
            
            # Create malicious tar
            malicious_tar = self.create_malicious_tar(temp_path)
            
            # Should raise SecurityError due to path traversal
            with pytest.raises(SecurityError):
                TarExtractor.safe_extract_tar(malicious_tar, target_dir)

    def test_safe_extract_tar_safe_archive(self):
        """Test that safe tar archives extract correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            target_dir = temp_path / "extract"
            target_dir.mkdir()
            
            # Create safe tar
            safe_tar = temp_path / "safe.tar.gz"
            with tarfile.open(safe_tar, "w:gz") as tar:
                safe_info = tarfile.TarInfo("safe_file.txt")
                safe_info.size = 12
                tar.addfile(safe_info, io.BytesIO(b"safe content"))
            
            # Should extract without issues
            TarExtractor.safe_extract_tar(safe_tar, target_dir)
            
            # Verify file was extracted
            extracted_file = target_dir / "safe_file.txt"
            assert extracted_file.exists()
            assert extracted_file.read_text() == "safe content"


class TestFileOperationValidator:
    """Test file operation validation utilities."""

    def test_validate_server_file_path_safe(self):
        """Test that safe server file paths are allowed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            server_dir = base_dir / "test-server"
            server_dir.mkdir()
            
            # Test valid file path within server
            result = FileOperationValidator.validate_server_file_path(
                "test-server", "config/server.properties", base_dir
            )
            
            expected = server_dir / "config" / "server.properties"
            assert result == expected.resolve()

    def test_validate_server_file_path_traversal(self):
        """Test that path traversal in file paths is blocked."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            
            # Test path traversal in file path
            with pytest.raises(SecurityError):
                FileOperationValidator.validate_server_file_path(
                    "test-server", "../../../etc/passwd", base_dir
                )

    def test_validate_server_file_path_invalid_server_name(self):
        """Test that invalid server names are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            
            # Test invalid server name
            with pytest.raises(SecurityError):
                FileOperationValidator.validate_server_file_path(
                    "../../../etc", "passwd", base_dir
                )


class TestServerServiceSecurity:
    """Test security fixes in server service."""

    def test_server_validation_service_rejects_malicious_names(self):
        """Test that server validation rejects malicious names."""
        validation_service = ServerValidationService()
        
        malicious_names = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "../../app/core/database.py",
            "normal/../../../etc/hosts",
        ]
        
        for name in malicious_names:
            with pytest.raises(InvalidRequestException):
                validation_service.validate_server_directory(name)

    @pytest.mark.asyncio
    async def test_filesystem_service_rejects_malicious_names(self):
        """Test that filesystem service rejects malicious server names."""
        filesystem_service = ServerFileSystemService()
        
        malicious_names = [
            "../../../tmp/malicious",
            "..\\..\\..\\windows\\temp",
            "normal/../../../tmp/hack",
        ]
        
        for name in malicious_names:
            with pytest.raises(InvalidRequestException):
                await filesystem_service.create_server_directory(name)

    @pytest.mark.asyncio
    async def test_filesystem_service_allows_safe_names(self):
        """Test that filesystem service allows safe server names."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock the base directory
            filesystem_service = ServerFileSystemService()
            original_base = filesystem_service.base_directory
            filesystem_service.base_directory = Path(temp_dir)
            
            try:
                # Test safe names
                safe_names = ["test-server", "my_server", "server123"]
                
                for name in safe_names:
                    server_dir = await filesystem_service.create_server_directory(name)
                    assert server_dir.exists()
                    assert server_dir.name == name
                    assert str(server_dir).startswith(str(Path(temp_dir)))
            finally:
                filesystem_service.base_directory = original_base


class TestBackupServiceSecurity:
    """Test security fixes in backup service."""

    def test_backup_file_service_secure_extraction(self):
        """Test that backup extraction uses secure methods."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            backups_dir = temp_path / "backups"
            backups_dir.mkdir()
            
            backup_service = BackupFileService(backups_dir)
            
            # Create malicious backup file
            malicious_backup = temp_path / "malicious_backup.tar.gz"
            with tarfile.open(malicious_backup, "w:gz") as tar:
                # Add malicious file
                malicious_info = tarfile.TarInfo("../../../etc/passwd")
                malicious_info.size = 7
                tar.addfile(malicious_info, io.BytesIO(b"hacked\n"))
            
            # Create mock backup and server objects
            mock_backup = Mock()
            mock_backup.file_path = str(malicious_backup)
            
            mock_server = Mock()
            mock_server.directory_path = str(temp_path / "target")
            
            # Should raise FileOperationException (which wraps SecurityError) when extracting malicious backup
            with pytest.raises(FileOperationException):
                backup_service._extract_backup_to_directory(
                    malicious_backup, Path(mock_server.directory_path)
                )


class TestIntegrationSecurity:
    """Integration tests for security across services."""

    def test_server_creation_path_traversal_protection(self):
        """Test end-to-end protection against path traversal in server creation."""
        # This test would require setting up a full test database and services
        # For now, we test the core validation logic
        
        malicious_requests = [
            {"name": "../../../etc/passwd"},
            {"name": "..\\..\\..\\windows\\system32"},
            {"name": "normal/../../../tmp/hack"},
        ]
        
        validation_service = ServerValidationService()
        
        for request_data in malicious_requests:
            with pytest.raises(InvalidRequestException):
                validation_service.validate_server_directory(request_data["name"])

    def test_file_operations_path_validation(self):
        """Test that file operations validate paths correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            
            # Test that malicious file paths are rejected
            malicious_paths = [
                "../../../etc/passwd",
                "..\\..\\..\\windows\\system32\\config",
                "normal/../../../tmp/hack",
            ]
            
            for path in malicious_paths:
                with pytest.raises(SecurityError):
                    FileOperationValidator.validate_server_file_path(
                        "test-server", path, base_dir
                    )


# Patch imports that might not exist during testing
try:
    from app.core.exceptions import InvalidRequestException, FileOperationException
except ImportError:
    # Create mock exceptions for testing
    class InvalidRequestException(Exception):
        pass
    
    class FileOperationException(Exception):
        pass