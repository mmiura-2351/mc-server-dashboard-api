"""Security tests for `FileOperationValidator`.

Split from `tests/test_security.py` (Issue #170) — covers server-scoped file
path validation including traversal detection in
`app.core.security.FileOperationValidator`.
"""

import tempfile
from pathlib import Path

import pytest

from app.core.security import FileOperationValidator, SecurityError


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
