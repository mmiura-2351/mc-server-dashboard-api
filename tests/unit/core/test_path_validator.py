"""Security tests for `PathValidator`.

Split from `tests/test_security.py` (Issue #170) — covers safe-name validation,
path traversal protection, and directory sanitisation behaviour of
`app.core.security.PathValidator`.
"""

import tempfile
from pathlib import Path

import pytest

from app.core.security import PathValidator, SecurityError


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
