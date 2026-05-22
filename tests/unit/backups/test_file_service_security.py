"""Security tests for backup file service extraction/upload paths.

Split from `tests/test_security.py` (Issue #170) — covers tar-archive
extraction and upload security validation in
`app.backups.application.file_service.BackupFileService` and the new
DI-shaped `BackupService`.
"""

import io
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.backups.application.file_service import BackupFileService
from app.core.exceptions import FileOperationException


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
        """Test that backup upload validates security correctly.

        Migrated off the legacy `app.backups.adapters.legacy.BackupService`
        facade (Issue #294): constructs the new DI-shaped
        `app.backups.application.service.BackupService` directly with
        in-memory fakes so the upload security path is exercised without
        touching the database. The verified invariant is unchanged —
        an upload containing a path-traversing tar entry must be
        rejected with `FileOperationException("Security validation
        failed: ...")` from `TarExtractor.validate_archive_safety`.
        """
        from app.backups.application.service import BackupService
        from tests.unit.backups.fakes import (
            FakeBackupsUnitOfWork,
            FakeServerReadPort,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            backups_dir = temp_path / "backups"

            # Seed the server-read port so `_get_server_or_raise(1)` resolves
            # to a fake server entity — equivalent to the legacy
            # `BackupValidationService.validate_server_for_backup` patch
            # which used to inject a mock server with id=1.
            server_read = FakeServerReadPort()
            server_read.seed(id=1, directory_path=str(temp_path / "srv"))

            uow = FakeBackupsUnitOfWork()
            backup_service = BackupService(
                uow=uow,
                server_read=server_read,
                backups_directory=backups_dir,
            )

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

            # Should raise FileOperationException due to security validation failure
            try:
                result = await backup_service.upload_backup(
                    server_id=1, file=mock_upload_file
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

            # UoW must not commit on security failure (pre-commit rollback path).
            assert uow.committed == 0, (
                f"UoW should not commit on security failure, got committed={uow.committed}"
            )
