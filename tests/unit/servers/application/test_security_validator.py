"""Security tests for server service path/name validation.

Split from `tests/test_security.py` (Issue #170) — exercises
`ServerValidationService` and `ServerFileSystemService` to confirm malicious
server names are rejected before any filesystem operation runs.
"""

import tempfile
from pathlib import Path

import pytest

from app.core.exceptions import InvalidRequestException
from app.core.security import PathValidator
from app.servers.adapters._legacy_helpers import ServerValidationService
from app.servers.application.service import ServerFileSystemService


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
