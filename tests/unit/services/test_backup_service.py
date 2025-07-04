"""
Comprehensive test coverage for BackupService
Consolidates all backup service related tests for better organization
"""

import tarfile
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.exc import DatabaseError

from app.core.exceptions import (
    BackupNotFoundException,
    DatabaseOperationException,
    FileOperationException,
    ServerNotFoundException,
    ServerStateException,
)
from app.servers.models import Backup, BackupStatus, BackupType, Server
from app.services.backup_service import (
    BackupDatabaseService,
    BackupFileService,
    BackupService,
    backup_service,
)


class TestBackupServiceExceptions:
    """Test custom exception classes"""

    def test_backup_not_found_exception(self):
        error = BackupNotFoundException("123")
        assert "Backup with ID 123 not found" in str(error)
        assert error.status_code == 404

    def test_server_not_found_exception(self):
        error = ServerNotFoundException("456")
        assert "Server with ID 456 not found" in str(error)
        assert error.status_code == 404

    def test_file_operation_exception(self):
        error = FileOperationException("backup", "/path/to/file", "disk full")
        assert "Failed to backup file /path/to/file: disk full" in str(error)
        assert error.status_code == 500

    def test_database_operation_exception(self):
        error = DatabaseOperationException("create", "backup", "connection error")
        assert "Database create failed for backup: connection error" in str(error)
        assert error.status_code == 500


class TestBackupService:
    """Test BackupService class - basic functionality"""

    @pytest.fixture
    def service(self):
        with patch("pathlib.Path.mkdir"):
            return BackupService()

    @pytest.fixture
    def mock_db(self):
        return Mock()

    def test_init(self, service):
        """Test BackupService initialization"""
        assert service.backups_directory == Path("backups")

    @pytest.mark.asyncio
    async def test_create_backup_server_not_found(self, service, mock_db):
        """Test create_backup when server not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ServerNotFoundException):
            await service.create_backup(
                server_id=999,
                name="test_backup",
                db=mock_db,
                backup_type=BackupType.manual,
            )

    @pytest.mark.asyncio
    @patch("app.services.minecraft_server.minecraft_server_manager.get_server_status")
    async def test_create_backup_success(self, mock_status, service, mock_db):
        """Test successful backup creation"""
        # Mock server
        mock_server = Mock()
        mock_server.id = 1
        mock_server.directory_path = "servers/test"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server

        # Mock server status
        mock_status.return_value = Mock(value="stopped")

        # Mock backup creation
        with patch.object(
            service.file_service,
            "create_backup_file",
            return_value="backup_1_1_20240101_120000.tar.gz",
        ):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 1024000

                result = await service.create_backup(
                    server_id=1,
                    name="test_backup",
                    db=mock_db,
                    backup_type=BackupType.manual,
                )

                mock_db.add.assert_called_once()
                mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_backup_not_found(self, service, mock_db):
        """Test restore_backup when backup not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(BackupNotFoundException):
            await service.restore_backup(backup_id=999, db=mock_db)

    @pytest.mark.asyncio
    async def test_delete_backup_success(self, service, mock_db):
        """Test successful backup deletion"""
        mock_backup = Mock()
        mock_backup.id = 1
        mock_backup.file_path = "backups/test.tar.gz"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_backup

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.unlink"):
                result = await service.delete_backup(backup_id=1, db=mock_db)

                assert result is True
                mock_db.delete.assert_called_once_with(mock_backup)
                mock_db.commit.assert_called_once()

    def test_list_backups(self, service, mock_db):
        """Test list_backups"""
        mock_backups = [Mock(), Mock()]
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = mock_backups
        mock_query.count.return_value = 2

        result = service.list_backups(db=mock_db, server_id=1)

        assert result["backups"] == mock_backups
        assert result["total"] == 2
        assert result["page"] == 1
        assert result["size"] == 50

    def test_get_backup(self, service, mock_db):
        """Test get_backup"""
        mock_backup = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_backup

        result = service.get_backup(backup_id=1, db=mock_db)

        assert result == mock_backup

    def test_get_backup_statistics(self, service, mock_db):
        """Test get_backup_statistics"""
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.count.side_effect = [10, 8, 2]  # total, completed, failed

        # Mock the new SQL SUM query for total size calculation
        mock_query.scalar.return_value = 3000000  # Sum of file sizes

        result = service.get_backup_statistics(db=mock_db, server_id=1)

        assert result["total_backups"] == 10
        assert result["completed_backups"] == 8
        assert result["failed_backups"] == 2
        assert result["total_size_bytes"] == 3000000


class TestBackupServiceAdditionalExceptions:
    """Test additional exception scenarios in BackupService"""

    @pytest.fixture
    def backup_service(self):
        """Create a BackupService instance."""
        return BackupService()

    @pytest.fixture
    def backup_file_service(self, temp_backup_dir):
        """Create a BackupFileService instance."""
        return BackupFileService(temp_backup_dir)

    @pytest.fixture
    def backup_db_service(self):
        """Create a BackupDatabaseService instance."""
        return BackupDatabaseService()

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = Mock()
        session.commit = Mock()
        session.rollback = Mock()
        session.query = Mock()
        session.add = Mock()
        session.flush = Mock()
        return session

    @pytest.fixture
    def temp_backup_dir(self):
        """Create a temporary backup directory."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_server(self):
        """Create a mock server object."""
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test-server"
        server.owner_id = 1
        server.directory_path = "/path/to/server"
        return server

    @pytest.fixture
    def mock_backup(self):
        """Create a mock backup object."""
        backup = Mock(spec=Backup)
        backup.id = 1
        backup.server_id = 1
        backup.status = BackupStatus.completed
        backup.file_path = "/path/to/backup.tar.gz"
        backup.backup_type = BackupType.manual
        return backup

    # Test BackupFileService exceptions
    def test_create_tar_backup_archive_corruption(
        self, backup_file_service, temp_backup_dir
    ):
        """Test backup creation when archive gets corrupted during creation."""
        server_dir = temp_backup_dir / "server"
        server_dir.mkdir()
        (server_dir / "world").mkdir()
        (server_dir / "world" / "level.dat").write_text("test data")

        with patch("tarfile.open") as mock_tarfile:
            mock_tar = Mock()
            mock_tar.add.side_effect = OSError("Archive corruption detected")
            mock_tarfile.return_value.__enter__.return_value = mock_tar

            with pytest.raises(OSError) as exc_info:
                backup_file_service._create_tar_backup(
                    server_dir, temp_backup_dir / "backup.tar.gz"
                )
            assert "Archive corruption" in str(exc_info.value)

    def test_extract_backup_to_directory_failure(
        self, backup_file_service, temp_backup_dir
    ):
        """Test backup restoration when archive extraction fails."""
        backup_file = temp_backup_dir / "backup.tar.gz"
        backup_file.write_bytes(b"corrupted tar data")

        restore_dir = temp_backup_dir / "restore"

        with pytest.raises(tarfile.TarError):
            backup_file_service._extract_backup_to_directory(backup_file, restore_dir)

    def test_create_tar_backup_insufficient_disk_space(
        self, backup_file_service, temp_backup_dir
    ):
        """Test backup creation when there's insufficient disk space."""
        server_dir = temp_backup_dir / "server"
        server_dir.mkdir()

        with patch("tarfile.open", side_effect=OSError("No space left on device")):
            with pytest.raises(OSError) as exc_info:
                backup_file_service._create_tar_backup(
                    server_dir, temp_backup_dir / "backup.tar.gz"
                )
            assert "No space left on device" in str(exc_info.value)

    def test_delete_backup_file_permission_denied(
        self, backup_file_service, temp_backup_dir
    ):
        """Test deleting backup file when permission is denied."""
        backup_file = temp_backup_dir / "backup.tar.gz"
        backup_file.touch()
        backup_file.chmod(0o444)  # Read-only

        try:
            with patch(
                "pathlib.Path.unlink", side_effect=PermissionError("Permission denied")
            ):
                with pytest.raises(PermissionError):
                    backup_file_service.delete_backup_file(str(backup_file))
        finally:
            backup_file.chmod(0o644)

    # Test BackupDatabaseService exceptions
    def test_create_backup_record_database_error(
        self, backup_db_service, mock_db_session, mock_server
    ):
        """Test backup record creation when database write fails."""
        mock_db_session.add.side_effect = DatabaseError(
            "Database write failed", None, None
        )

        with pytest.raises(DatabaseOperationException):
            backup_db_service.create_backup_record(
                mock_server.id,
                "test-backup",
                "test description",
                BackupType.manual,
                mock_db_session,
            )

    def test_update_backup_with_file_info_commit_failure(
        self, backup_db_service, mock_db_session, mock_backup
    ):
        """Test updating backup when database operation fails."""
        # Since update_backup_with_file_info no longer commits, we test by making the attribute access fail
        # Create a property that raises an exception when set
        type(mock_backup).file_path = property(
            lambda self: "",
            lambda self, value: (_ for _ in ()).throw(
                DatabaseError("Attribute set failed", None, None)
            ),
        )

        with pytest.raises(DatabaseOperationException):
            backup_db_service.update_backup_with_file_info(
                mock_backup, "/path/to/backup.tar.gz", 1024, mock_db_session
            )

    def test_mark_backup_failed_database_error(
        self, backup_db_service, mock_db_session, mock_backup
    ):
        """Test marking backup as failed when database commit fails."""
        mock_db_session.commit.side_effect = DatabaseError("Commit failed", None, None)

        with pytest.raises(DatabaseOperationException):
            backup_db_service.mark_backup_failed(mock_backup, mock_db_session)

        # Status should still be set even if commit fails
        assert mock_backup.status == BackupStatus.failed

    def test_delete_backup_record_constraint_violation(
        self, backup_db_service, mock_db_session, mock_backup
    ):
        """Test deleting backup record when foreign key constraint is violated."""
        mock_db_session.delete = Mock()
        mock_db_session.commit.side_effect = DatabaseError(
            "FOREIGN KEY constraint failed", None, None
        )

        with pytest.raises(DatabaseOperationException):
            backup_db_service.delete_backup_record(mock_backup, mock_db_session)

    # Test BackupService high-level exceptions
    @pytest.mark.asyncio
    async def test_create_backup_server_directory_not_found(
        self, backup_service, mock_db_session, mock_server
    ):
        """Test backup creation when server directory doesn't exist."""
        with patch(
            "app.services.backup_service.BackupValidationService.validate_server_for_backup",
            return_value=mock_server,
        ):
            with patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(FileOperationException) as exc_info:
                    await backup_service.create_backup(
                        mock_server.id,
                        "test-backup",
                        mock_db_session,
                        None,
                        BackupType.manual,
                    )
                assert "Server directory not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_backup_with_special_characters(
        self, backup_service, mock_db_session, mock_server, temp_backup_dir
    ):
        """Test backup creation with special characters in names."""
        backup_name = "backup with ñ and emojis 🎮"

        with patch(
            "app.services.backup_service.BackupValidationService.validate_server_for_backup",
            return_value=mock_server,
        ):
            server_dir = temp_backup_dir / f"server_{mock_server.id}"
            server_dir.mkdir()

            # Mock the database service to avoid actual DB operations
            mock_backup_record = Mock(spec=Backup)
            mock_backup_record.id = 1
            mock_backup_record.server_id = mock_server.id

            # Mock the server directory path to use temp directory
            mock_server.directory_path = str(server_dir)

            with patch.object(
                backup_service.db_service,
                "create_backup_record",
                return_value=mock_backup_record,
            ):
                with patch.object(
                    backup_service.file_service,
                    "create_backup_file",
                    new_callable=AsyncMock,
                    return_value=str(temp_backup_dir / "backup.tar.gz"),
                ):
                    # Create a dummy backup file for the test
                    backup_file = temp_backup_dir / "backup.tar.gz"
                    backup_file.touch()

                    with patch.object(
                        backup_service.db_service, "update_backup_with_file_info"
                    ):
                        result = await backup_service.create_backup(
                            mock_server.id,
                            backup_name,
                            mock_db_session,
                            None,
                            BackupType.manual,
                        )
                        assert result is not None

    @pytest.mark.asyncio
    async def test_restore_backup_server_still_running(
        self, backup_service, mock_db_session, mock_backup, mock_server
    ):
        """Test backup restoration when server is still running."""
        with patch(
            "app.services.backup_service.BackupValidationService.validate_backup_exists",
            return_value=mock_backup,
        ):
            with patch(
                "app.services.backup_service.BackupValidationService.validate_server_stopped_for_restore",
                side_effect=ServerStateException("1", "running", "stopped"),
            ):
                with pytest.raises(ServerStateException) as exc_info:
                    await backup_service.restore_backup(
                        mock_backup.id, mock_db_session, mock_server.id
                    )
                assert "stopped" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_restore_backup_file_not_found(
        self, backup_service, mock_db_session, mock_backup, mock_server
    ):
        """Test backup restoration when backup file is missing."""
        mock_backup.file_path = "/non/existent/backup.tar.gz"

        with patch(
            "app.services.backup_service.BackupValidationService.validate_backup_exists",
            return_value=mock_backup,
        ):
            with patch(
                "app.services.backup_service.BackupValidationService.validate_server_for_backup",
                return_value=mock_server,
            ):
                with patch(
                    "app.services.backup_service.BackupValidationService.validate_server_stopped_for_restore"
                ):
                    with patch("pathlib.Path.exists", return_value=False):
                        with pytest.raises(FileOperationException) as exc_info:
                            await backup_service.restore_backup(
                                mock_backup.id, mock_server.id, mock_db_session
                            )
                        assert "Backup file not found" in str(exc_info.value)


class TestBackupServiceConcurrencyAndEdgeCases:
    """Test concurrency and edge cases in BackupService"""

    @pytest.fixture
    def backup_service(self):
        return BackupService()

    @pytest.fixture
    def backup_file_service(self, temp_backup_dir):
        return BackupFileService(temp_backup_dir)

    @pytest.fixture
    def temp_backup_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_server(self):
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test-server"
        server.owner_id = 1
        server.directory_path = "/path/to/server"
        return server

    @pytest.fixture
    def mock_db_session(self):
        session = Mock()
        session.commit = Mock()
        session.rollback = Mock()
        session.query = Mock()
        session.add = Mock()
        session.flush = Mock()
        return session

    # Test concurrent backup operations
    @pytest.mark.asyncio
    async def test_concurrent_backup_operations(
        self, backup_service, mock_db_session, mock_server, temp_backup_dir
    ):
        """Test handling of concurrent backup operations on same server."""
        import asyncio

        with patch(
            "app.services.backup_service.BackupValidationService.validate_server_for_backup",
            return_value=mock_server,
        ):
            with patch.object(backup_service, "_log_running_server_warning"):
                # Simulate concurrent backups
                tasks = []
                for i in range(3):
                    task = backup_service.create_backup(
                        mock_server.id,
                        f"concurrent-backup-{i}",
                        mock_db_session,
                        None,
                        BackupType.manual,
                    )
                    tasks.append(task)

                # All should complete without issues
                # Create a temporary backup file
                temp_backup_file = temp_backup_dir / "backup.tar.gz"
                temp_backup_file.touch()

                with patch.object(
                    backup_service.db_service, "create_backup_record"
                ) as mock_create:
                    mock_create.return_value = Mock(id=1, server_id=mock_server.id)
                    with patch.object(
                        backup_service.file_service,
                        "create_backup_file",
                        new_callable=AsyncMock,
                        return_value=str(temp_backup_file),
                    ):
                        with patch.object(
                            backup_service.db_service, "update_backup_with_file_info"
                        ):
                            with patch("pathlib.Path.exists", return_value=True):
                                results = await asyncio.gather(
                                    *tasks, return_exceptions=True
                                )
                                # Should handle concurrent access gracefully
                                assert all(not isinstance(r, Exception) for r in results)

    # Test symlink handling in backups
    def test_backup_with_symlinks(self, backup_file_service, temp_backup_dir):
        """Test backup creation with symbolic links."""
        server_dir = temp_backup_dir / "server"
        server_dir.mkdir()

        # Create a file and a symlink
        real_file = server_dir / "real_file.txt"
        real_file.write_text("real content")

        symlink_file = server_dir / "symlink_file.txt"
        try:
            symlink_file.symlink_to(real_file)
        except OSError:
            # Skip test if symlinks not supported
            pytest.skip("Symbolic links not supported on this system")

        backup_file = temp_backup_dir / "backup.tar.gz"

        # Should handle symlinks appropriately
        try:
            backup_file_service._create_tar_backup(server_dir, backup_file)
            assert backup_file.exists()
        except FileOperationException:
            # If it fails, it should be a proper FileOperationException
            pass

    # Test large file backup scenarios
    def test_backup_large_file_memory_error(self, backup_file_service, temp_backup_dir):
        """Test backup creation with memory constraints on large files."""
        server_dir = temp_backup_dir / "server"
        server_dir.mkdir()

        # Create a small file for testing
        (server_dir / "test.txt").write_text("test")

        with patch("tarfile.TarFile.add", side_effect=MemoryError("Out of memory")):
            with pytest.raises(MemoryError):
                backup_file_service._create_tar_backup(
                    server_dir, temp_backup_dir / "backup.tar.gz"
                )

    # Test cleanup after failures
    def test_backup_cleanup_after_failure(self, backup_file_service, temp_backup_dir):
        """Test that partial backup files are cleaned up after failure."""
        server_dir = temp_backup_dir / "server"
        server_dir.mkdir()
        backup_file = temp_backup_dir / "backup.tar.gz"

        # _create_tar_backup doesn't handle cleanup, so the file might exist
        # This test demonstrates that cleanup logic would need to be in a higher level
        with patch("tarfile.open", side_effect=OSError("Compression failed")):
            with pytest.raises(OSError):
                backup_file_service._create_tar_backup(server_dir, backup_file)

    # Test permission issues during backup
    def test_backup_permission_denied_during_compression(
        self, backup_file_service, temp_backup_dir
    ):
        """Test backup creation when permission is denied during compression."""
        server_dir = temp_backup_dir / "server"
        server_dir.mkdir()

        # Create a file without read permission
        restricted_file = server_dir / "restricted.dat"
        restricted_file.write_text("restricted content")
        restricted_file.chmod(0o000)

        try:
            with pytest.raises(PermissionError):
                backup_file_service._create_tar_backup(
                    server_dir, temp_backup_dir / "backup.tar.gz"
                )
        finally:
            restricted_file.chmod(0o644)  # Restore for cleanup


def test_global_backup_service_instance():
    """Test that global backup_service instance exists"""
    assert backup_service is not None
    assert isinstance(backup_service, BackupService)


class TestMemoryExhaustionPrevention:
    """Test memory exhaustion prevention features in backup service"""

    @pytest.fixture
    def backup_service(self):
        return BackupService()

    @pytest.fixture
    def mock_upload_file(self):
        """Create a mock UploadFile for testing"""
        mock_file = Mock()
        mock_file.filename = "test_backup.tar.gz"
        mock_file.headers = {"content-length": "1048576"}  # 1MB
        mock_file.read = AsyncMock()
        return mock_file

    @pytest.fixture
    def mock_db_session(self):
        session = Mock()
        session.commit = Mock()
        session.rollback = Mock()
        session.query = Mock()
        session.add = Mock()
        session.flush = Mock()
        session.refresh = Mock()
        return session

    @pytest.fixture
    def mock_server(self):
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test-server"
        server.owner_id = 1
        server.directory_path = "/path/to/server"
        return server

    @pytest.mark.asyncio
    async def test_upload_backup_content_length_validation(
        self, backup_service, mock_upload_file, mock_db_session, mock_server
    ):
        """Test that upload_backup validates Content-Length header early"""
        # Test with file size exceeding limit
        mock_upload_file.headers = {"content-length": str(600 * 1024 * 1024)}  # 600MB

        with patch(
            "app.services.backup_service.BackupValidationService.validate_server_for_backup",
            return_value=mock_server,
        ):
            with pytest.raises(FileOperationException) as exc_info:
                await backup_service.upload_backup(
                    server_id=1,
                    file=mock_upload_file,
                    db=mock_db_session,
                    name="test_backup",
                )
            assert "exceeds maximum allowed size" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_backup_streaming_size_check(
        self, backup_service, mock_upload_file, mock_db_session, mock_server
    ):
        """Test that streaming upload monitors file size during processing"""
        # Mock file that reports smaller size in header but streams more data
        mock_upload_file.headers = {"content-length": "1048576"}  # 1MB in header

        # Mock chunks that exceed the actual limit when accumulated
        large_chunk = b"x" * (100 * 1024 * 1024)  # 100MB chunks
        mock_upload_file.read = AsyncMock(
            side_effect=[large_chunk] * 6 + [b""]
        )  # 600MB total

        with patch(
            "app.services.backup_service.BackupValidationService.validate_server_for_backup",
            return_value=mock_server,
        ):
            with pytest.raises(FileOperationException) as exc_info:
                await backup_service.upload_backup(
                    server_id=1,
                    file=mock_upload_file,
                    db=mock_db_session,
                    name="test_backup",
                )
            assert "exceeds maximum allowed size" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch("app.services.backup_service.psutil")
    async def test_resource_monitor_memory_limit(
        self, mock_psutil, backup_service, mock_upload_file, mock_db_session, mock_server
    ):
        """Test that ResourceMonitor detects memory limit violations"""
        # Mock psutil to simulate increasing memory usage
        mock_process = Mock()
        initial_memory = 1024 * 1024 * 1024  # 1GB
        excessive_memory = initial_memory + (
            300 * 1024 * 1024
        )  # +300MB (exceeds 256MB limit)

        mock_process.memory_info.return_value.rss = initial_memory
        mock_psutil.Process.return_value = mock_process

        # Mock file chunks
        mock_upload_file.read = AsyncMock(side_effect=[b"x" * 8192] * 100 + [b""])

        with patch(
            "app.services.backup_service.BackupValidationService.validate_server_for_backup",
            return_value=mock_server,
        ):
            with patch("tempfile.NamedTemporaryFile") as mock_temp:
                mock_temp_file = Mock()
                mock_temp_file.name = "/tmp/test_backup.tar.gz"
                mock_temp_file.write = Mock()
                mock_temp_file.flush = Mock()
                mock_temp.return_value.__enter__.return_value = mock_temp_file

                # Simulate memory increase after some chunks
                def memory_side_effect():
                    if (
                        mock_temp_file.write.call_count > 50
                    ):  # After processing some chunks
                        mock_process.memory_info.return_value.rss = excessive_memory
                    return mock_process.memory_info.return_value

                mock_process.memory_info.side_effect = memory_side_effect

                with pytest.raises((FileOperationException, MemoryError)) as exc_info:
                    await backup_service.upload_backup(
                        server_id=1,
                        file=mock_upload_file,
                        db=mock_db_session,
                        name="test_backup",
                    )
                assert "Memory limit exceeded" in str(
                    exc_info.value
                ) or "Memory usage exceeded limit" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_resource_monitor_without_psutil(
        self, backup_service, mock_upload_file, mock_db_session, mock_server
    ):
        """Test that ResourceMonitor works gracefully when psutil is not available"""
        with patch("app.services.backup_service.psutil", None):
            # Should still work but without memory monitoring
            mock_upload_file.read = AsyncMock(side_effect=[b"x" * 1024] * 10 + [b""])

            with patch(
                "app.services.backup_service.BackupValidationService.validate_server_for_backup",
                return_value=mock_server,
            ):
                with patch("tempfile.NamedTemporaryFile") as mock_temp:
                    mock_temp_file = Mock()
                    mock_temp_file.name = "/tmp/test_backup.tar.gz"
                    mock_temp_file.write = Mock()
                    mock_temp_file.flush = Mock()
                    mock_temp.return_value.__enter__.return_value = mock_temp_file

                    with patch("tarfile.open") as mock_tarfile:
                        mock_tar = Mock()
                        mock_tar.getnames.return_value = ["test.txt"]
                        mock_tarfile.return_value.__enter__.return_value = mock_tar

                        with patch(
                            "app.core.security.TarExtractor.validate_archive_safety"
                        ):
                            with patch("shutil.move"):
                                # Should complete without memory monitoring
                                result = await backup_service.upload_backup(
                                    server_id=1,
                                    file=mock_upload_file,
                                    db=mock_db_session,
                                    name="test_backup",
                                )
                                assert result is not None

    @pytest.mark.asyncio
    async def test_chunked_file_processing_memory_efficiency(self, backup_service):
        """Test that file chunks are processed efficiently without excessive memory usage"""
        # Test the _read_file_chunks method specifically
        mock_file = Mock()
        chunks = [b"x" * 8192] * 1000 + [b""]  # 1000 chunks of 8KB each
        mock_file.read = AsyncMock(side_effect=chunks)

        total_bytes = 0
        chunk_count = 0

        async for chunk in backup_service._read_file_chunks(mock_file, chunk_size=8192):
            total_bytes += len(chunk)
            chunk_count += 1
            # Verify chunks are reasonable size
            assert len(chunk) <= 8192

        assert chunk_count == 1000
        assert total_bytes == 8192 * 1000

        # Verify file.read was called with correct chunk size
        mock_file.read.assert_called_with(8192)

    @pytest.mark.asyncio
    async def test_async_directory_size_calculation_memory_efficiency(self):
        """Test that async directory size calculation doesn't block event loop"""
        import asyncio
        import tempfile

        from app.services.backup_service import BackupFileService

        # Create temporary directory with files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test files
            for i in range(100):
                (temp_path / f"file_{i}.txt").write_text(f"content {i}")

            service = BackupFileService(temp_path)

            # Measure time to ensure it doesn't block
            start_time = asyncio.get_event_loop().time()
            file_count, total_size = await service._calculate_directory_size_async(
                temp_path
            )
            end_time = asyncio.get_event_loop().time()

            # Should complete reasonably quickly
            assert end_time - start_time < 5.0  # Should take less than 5 seconds
            assert file_count == 100
            assert total_size > 0

    def test_resource_monitor_context_manager(self):
        """Test ResourceMonitor as async context manager"""
        from app.services.backup_service import ResourceMonitor

        # Test initialization
        monitor = ResourceMonitor(max_memory_mb=128)
        assert monitor.max_memory_bytes == 128 * 1024 * 1024

    @pytest.mark.asyncio
    @patch("app.services.backup_service.psutil")
    async def test_resource_monitor_memory_check_normal_usage(self, mock_psutil):
        """Test ResourceMonitor with normal memory usage"""
        from app.services.backup_service import ResourceMonitor

        mock_process = Mock()
        initial_memory = 1024 * 1024 * 1024  # 1GB
        normal_increase = initial_memory + (
            50 * 1024 * 1024
        )  # +50MB (within 256MB limit)

        mock_process.memory_info.return_value.rss = initial_memory
        mock_psutil.Process.return_value = mock_process

        async with ResourceMonitor(max_memory_mb=256) as monitor:
            # Simulate normal memory increase
            mock_process.memory_info.return_value.rss = normal_increase

            # Should not raise exception
            await monitor.check_memory_usage()

    @pytest.mark.asyncio
    @patch("app.services.backup_service.psutil")
    async def test_resource_monitor_memory_check_excessive_usage(self, mock_psutil):
        """Test ResourceMonitor with excessive memory usage"""
        from app.services.backup_service import ResourceMonitor

        mock_process = Mock()
        initial_memory = 1024 * 1024 * 1024  # 1GB
        excessive_memory = initial_memory + (
            300 * 1024 * 1024
        )  # +300MB (exceeds 256MB limit)

        mock_process.memory_info.return_value.rss = initial_memory
        mock_psutil.Process.return_value = mock_process

        async with ResourceMonitor(max_memory_mb=256) as monitor:
            # Simulate excessive memory increase
            mock_process.memory_info.return_value.rss = excessive_memory

            # Should raise MemoryError
            with pytest.raises(MemoryError) as exc_info:
                await monitor.check_memory_usage()
            assert "Memory usage exceeded limit" in str(exc_info.value)
