"""Cross-service integration tests for path-traversal protection.

Split from `tests/test_security.py` (Issue #170) — verifies the end-to-end
path-traversal protections exposed by `ServerValidationService` and
`FileOperationValidator` for the file/server domains.
"""

import tempfile
from pathlib import Path

import pytest

from app.core.exceptions import InvalidRequestException
from app.core.security import FileOperationValidator, SecurityError
from app.servers.adapters._legacy_helpers import ServerValidationService


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
