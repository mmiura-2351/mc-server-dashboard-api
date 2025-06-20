"""
Enhanced test coverage for FileHistoryService
Target: Increase coverage from 17.13% to 100%
Focus: All methods, error handling, edge cases, and file operations
"""

import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, mock_open, patch

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    FileOperationException,
    InvalidRequestException,
    ServerNotFoundException,
)
from app.files.models import FileEditHistory
from app.files.schemas import CleanupResult, FileHistoryRecord
from app.servers.models import Server
from app.services.file_history_service import FileHistoryService, file_history_service
from app.users.models import User


class TestFileHistoryServiceEnhancedCoverage:
    """Enhanced tests targeting 100% coverage"""

    @pytest.fixture
    def service(self):
        return FileHistoryService()

    @pytest.fixture
    def mock_db(self):
        db = Mock(spec=Session)
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        db.refresh = Mock()
        db.delete = Mock()
        db.query = Mock()
        return db

    @pytest.fixture
    def mock_server(self):
        server = Mock(spec=Server)
        server.id = 1
        server.directory_path = "./servers/1"
        return server

    @pytest.fixture
    def mock_user(self):
        user = Mock(spec=User)
        user.id = 1
        user.username = "testuser"
        return user

    @pytest.fixture
    def mock_history_record(self):
        record = Mock(spec=FileEditHistory)
        record.id = 1
        record.server_id = 1
        record.file_path = "server.properties"
        record.version_number = 1
        record.backup_file_path = (
            "./file_history/1/server.properties/v001_20250611_120000.properties"
        )
        record.file_size = 1024
        record.content_hash = "abcd1234"
        record.editor_user_id = 1
        record.description = "Test backup"
        record.created_at = datetime.now()
        record.editor = Mock()
        record.editor.username = "testuser"
        return record

    # Test create_version_backup method (lines 35-103)
    @pytest.mark.asyncio
    async def test_create_version_backup_success(self, service, mock_db):
        """Test successful version backup creation"""
        # Mock _normalize_file_path
        with patch.object(
            service, "_normalize_file_path", return_value="normalized/path.txt"
        ):
            # Mock directory creation
            with patch("pathlib.Path.mkdir") as mock_mkdir:
                # Mock content hash calculation
                expected_hash = hashlib.sha256("test content".encode("utf-8")).hexdigest()

                # Mock duplicate check
                with patch.object(service, "_is_duplicate_content", return_value=False):
                    # Mock version number
                    with patch.object(
                        service, "_get_next_version_number", return_value=1
                    ):
                        # Mock file write
                        mock_file = AsyncMock()
                        mock_file.write = AsyncMock()
                        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
                        mock_file.__aexit__ = AsyncMock(return_value=None)
                        with patch("aiofiles.open", return_value=mock_file):
                            # Mock cleanup
                            with patch.object(service, "_cleanup_excess_versions"):
                                # Mock _to_record_schema
                                mock_record = FileHistoryRecord(
                                    id=1,
                                    server_id=1,
                                    file_path="normalized/path.txt",
                                    version_number=1,
                                    backup_file_path="/tmp/backup/file.txt",
                                    file_size=12,
                                    content_hash=expected_hash,
                                    editor_user_id=1,
                                    editor_username="testuser",
                                    created_at=datetime.now(),
                                    description="Test backup",
                                )
                                with patch.object(
                                    service, "_to_record_schema", return_value=mock_record
                                ):
                                    result = await service.create_version_backup(
                                        server_id=1,
                                        file_path="test/path.txt",
                                        content="test content",
                                        user_id=1,
                                        description="Test backup",
                                        db=mock_db,
                                    )

                                    assert result is not None
                                    assert result.file_path == "normalized/path.txt"
                                    mock_mkdir.assert_called()
                                    mock_db.add.assert_called_once()
                                    mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_version_backup_duplicate_content(self, service, mock_db):
        """Test skipping backup for duplicate content"""
        with patch.object(service, "_normalize_file_path", return_value="test.txt"):
            with patch.object(service, "_is_duplicate_content", return_value=True):
                result = await service.create_version_backup(
                    server_id=1,
                    file_path="test.txt",
                    content="duplicate content",
                    db=mock_db,
                )

                assert result is None
                mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_version_backup_exception_handling(self, service, mock_db):
        """Test exception handling in create_version_backup"""
        with patch.object(
            service, "_normalize_file_path", side_effect=Exception("Normalization failed")
        ):
            with pytest.raises(
                FileOperationException, match="Failed to backup file test.txt"
            ):
                await service.create_version_backup(
                    server_id=1, file_path="test.txt", content="test content", db=mock_db
                )

    @pytest.mark.asyncio
    async def test_create_version_backup_file_write_error(self, service, mock_db):
        """Test file write error in create_version_backup"""
        with patch.object(service, "_normalize_file_path", return_value="test.txt"):
            with patch("pathlib.Path.mkdir"):
                with patch.object(service, "_is_duplicate_content", return_value=False):
                    with patch.object(
                        service, "_get_next_version_number", return_value=1
                    ):
                        with patch(
                            "aiofiles.open",
                            side_effect=PermissionError("Write permission denied"),
                        ):
                            with pytest.raises(FileOperationException):
                                await service.create_version_backup(
                                    server_id=1,
                                    file_path="test.txt",
                                    content="test content",
                                    db=mock_db,
                                )

    # Test get_file_history method (lines 105-126)
    @pytest.mark.asyncio
    async def test_get_file_history_success(self, service, mock_db, mock_history_record):
        """Test successful file history retrieval"""
        # Mock query chain
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_history_record]

        with patch.object(
            service, "_normalize_file_path", return_value="server.properties"
        ):
            with patch.object(service, "_to_record_schema") as mock_to_schema:
                mock_to_schema.return_value = FileHistoryRecord(
                    id=1,
                    server_id=1,
                    file_path="server.properties",
                    version_number=1,
                    backup_file_path="/tmp/backup/file.txt",
                    file_size=1024,
                    content_hash="abcd1234",
                    editor_user_id=1,
                    editor_username="testuser",
                    created_at=datetime.now(),
                    description="Test",
                )

                result = await service.get_file_history(
                    server_id=1, file_path="server.properties", limit=20, db=mock_db
                )

                assert len(result) == 1
                assert result[0].file_path == "server.properties"
                mock_query.order_by.assert_called_once()
                mock_query.limit.assert_called_with(20)

    @pytest.mark.asyncio
    async def test_get_file_history_empty_result(self, service, mock_db):
        """Test get_file_history with no results"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        with patch.object(
            service, "_normalize_file_path", return_value="nonexistent.txt"
        ):
            result = await service.get_file_history(
                server_id=1, file_path="nonexistent.txt", db=mock_db
            )

            assert result == []

    # Test get_version_content method (lines 128-164)
    @pytest.mark.asyncio
    async def test_get_version_content_success(
        self, service, mock_db, mock_history_record
    ):
        """Test successful version content retrieval"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_history_record

        with patch.object(
            service, "_normalize_file_path", return_value="server.properties"
        ):
            with patch("pathlib.Path.exists", return_value=True):
                # Mock aiofiles context manager properly
                mock_file = AsyncMock()
                mock_file.read = AsyncMock(return_value="test file content")
                mock_file.__aenter__ = AsyncMock(return_value=mock_file)
                mock_file.__aexit__ = AsyncMock(return_value=None)
                with patch("aiofiles.open", return_value=mock_file):
                    content, record = await service.get_version_content(
                        server_id=1,
                        file_path="server.properties",
                        version_number=1,
                        db=mock_db,
                    )

                    assert content == "test file content"
                    assert record == mock_history_record

    @pytest.mark.asyncio
    async def test_get_version_content_not_found(self, service, mock_db):
        """Test get_version_content when version not found"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with patch.object(
            service, "_normalize_file_path", return_value="server.properties"
        ):
            with pytest.raises(
                InvalidRequestException,
                match="Version 1 not found for file server.properties",
            ):
                await service.get_version_content(
                    server_id=1,
                    file_path="server.properties",
                    version_number=1,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_get_version_content_backup_file_not_found(
        self, service, mock_db, mock_history_record
    ):
        """Test get_version_content when backup file doesn't exist"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_history_record

        with patch.object(
            service, "_normalize_file_path", return_value="server.properties"
        ):
            with patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(FileOperationException, match="Backup file not found"):
                    await service.get_version_content(
                        server_id=1,
                        file_path="server.properties",
                        version_number=1,
                        db=mock_db,
                    )

    @pytest.mark.asyncio
    async def test_get_version_content_read_error(
        self, service, mock_db, mock_history_record
    ):
        """Test get_version_content when file read fails"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_history_record

        with patch.object(
            service, "_normalize_file_path", return_value="server.properties"
        ):
            with patch("pathlib.Path.exists", return_value=True):
                with patch(
                    "aiofiles.open", side_effect=PermissionError("Read permission denied")
                ):
                    with pytest.raises(FileOperationException):
                        await service.get_version_content(
                            server_id=1,
                            file_path="server.properties",
                            version_number=1,
                            db=mock_db,
                        )

    # Test restore_from_history method (lines 166-222)
    @pytest.mark.asyncio
    async def test_restore_from_history_success_with_backup(
        self, service, mock_db, mock_server
    ):
        """Test successful restore with backup creation"""
        # Mock get_version_content
        with patch.object(
            service, "get_version_content", return_value=("restored content", Mock())
        ):
            # Mock server query
            mock_db.query.return_value.filter.return_value.first.return_value = (
                mock_server
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                actual_file_path = Path(temp_dir) / "test.txt"
                mock_server.directory_path = temp_dir

                # Create existing file
                actual_file_path.write_text("current content")

                # Mock create_version_backup
                with patch.object(service, "create_version_backup") as mock_backup:
                    # Mock file write
                    mock_file = AsyncMock()
                    mock_file.write = AsyncMock()
                    mock_file.read = AsyncMock(return_value="current content")
                    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
                    mock_file.__aexit__ = AsyncMock(return_value=None)
                    with patch("aiofiles.open", return_value=mock_file):
                        content, backup_created = await service.restore_from_history(
                            server_id=1,
                            file_path="test.txt",
                            version_number=1,
                            user_id=1,
                            create_backup_before_restore=True,
                            description="Test restore",
                            db=mock_db,
                        )

                        assert content == "restored content"
                        assert backup_created is True
                        mock_backup.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_from_history_no_backup_needed(
        self, service, mock_db, mock_server
    ):
        """Test restore without backup creation"""
        with patch.object(
            service, "get_version_content", return_value=("restored content", Mock())
        ):
            mock_db.query.return_value.filter.return_value.first.return_value = (
                mock_server
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                mock_server.directory_path = temp_dir

                mock_file = AsyncMock()
                mock_file.write = AsyncMock()
                mock_file.__aenter__ = AsyncMock(return_value=mock_file)
                mock_file.__aexit__ = AsyncMock(return_value=None)
                with patch("aiofiles.open", return_value=mock_file):
                    with patch("pathlib.Path.mkdir"):
                        content, backup_created = await service.restore_from_history(
                            server_id=1,
                            file_path="test.txt",
                            version_number=1,
                            user_id=1,
                            create_backup_before_restore=False,
                            db=mock_db,
                        )

                        assert content == "restored content"
                        assert backup_created is False

    @pytest.mark.asyncio
    async def test_restore_from_history_server_not_found(self, service, mock_db):
        """Test restore when server not found"""
        with patch.object(
            service, "get_version_content", return_value=("content", Mock())
        ):
            mock_db.query.return_value.filter.return_value.first.return_value = None

            with pytest.raises(ServerNotFoundException, match="Server 1 not found"):
                await service.restore_from_history(
                    server_id=1,
                    file_path="test.txt",
                    version_number=1,
                    user_id=1,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_restore_from_history_backup_creation_fails(
        self, service, mock_db, mock_server
    ):
        """Test restore when backup creation fails"""
        with patch.object(
            service, "get_version_content", return_value=("restored content", Mock())
        ):
            mock_db.query.return_value.filter.return_value.first.return_value = (
                mock_server
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                actual_file_path = Path(temp_dir) / "test.txt"
                mock_server.directory_path = temp_dir
                actual_file_path.write_text("current content")

                # Mock backup creation to fail
                with patch.object(
                    service,
                    "create_version_backup",
                    side_effect=Exception("Backup failed"),
                ):
                    mock_file = AsyncMock()
                    mock_file.write = AsyncMock()
                    mock_file.read = AsyncMock(return_value="current content")
                    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
                    mock_file.__aexit__ = AsyncMock(return_value=None)
                    with patch("aiofiles.open", return_value=mock_file):
                        with patch("pathlib.Path.mkdir"):
                            content, backup_created = await service.restore_from_history(
                                server_id=1,
                                file_path="test.txt",
                                version_number=1,
                                user_id=1,
                                create_backup_before_restore=True,
                                db=mock_db,
                            )

                            assert content == "restored content"
                            assert backup_created is False  # Backup failed

    @pytest.mark.asyncio
    async def test_restore_from_history_write_error(self, service, mock_db, mock_server):
        """Test restore when file write fails"""
        with patch.object(
            service, "get_version_content", return_value=("restored content", Mock())
        ):
            mock_db.query.return_value.filter.return_value.first.return_value = (
                mock_server
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                mock_server.directory_path = temp_dir

                with patch(
                    "aiofiles.open",
                    side_effect=PermissionError("Write permission denied"),
                ):
                    with pytest.raises(FileOperationException):
                        await service.restore_from_history(
                            server_id=1,
                            file_path="test.txt",
                            version_number=1,
                            user_id=1,
                            db=mock_db,
                        )

    # Test delete_version method (lines 224-259)
    @pytest.mark.asyncio
    async def test_delete_version_success(self, service, mock_db, mock_history_record):
        """Test successful version deletion"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_history_record

        with patch.object(
            service, "_normalize_file_path", return_value="server.properties"
        ):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.unlink") as mock_unlink:
                    result = await service.delete_version(
                        server_id=1,
                        file_path="server.properties",
                        version_number=1,
                        db=mock_db,
                    )

                    assert result is True
                    mock_unlink.assert_called_once()
                    mock_db.delete.assert_called_with(mock_history_record)
                    mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_version_not_found(self, service, mock_db):
        """Test delete_version when version not found"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with patch.object(
            service, "_normalize_file_path", return_value="server.properties"
        ):
            with pytest.raises(
                InvalidRequestException,
                match="Version 1 not found for file server.properties",
            ):
                await service.delete_version(
                    server_id=1,
                    file_path="server.properties",
                    version_number=1,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_delete_version_file_not_exists(
        self, service, mock_db, mock_history_record
    ):
        """Test delete_version when backup file doesn't exist"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_history_record

        with patch.object(
            service, "_normalize_file_path", return_value="server.properties"
        ):
            with patch("pathlib.Path.exists", return_value=False):
                result = await service.delete_version(
                    server_id=1,
                    file_path="server.properties",
                    version_number=1,
                    db=mock_db,
                )

                assert result is True
                mock_db.delete.assert_called_with(mock_history_record)

    # Test get_server_statistics method (lines 261-297)
    @pytest.mark.asyncio
    async def test_get_server_statistics_success(self, service, mock_db):
        """Test successful server statistics retrieval"""
        # Mock stats query
        mock_stats = Mock()
        mock_stats.total_files = 5
        mock_stats.total_versions = 15
        mock_stats.total_storage = 102400
        mock_stats.oldest_version = datetime(2024, 1, 1)
        mock_stats.newest_version = datetime(2024, 12, 31)

        # Mock most_edited query
        mock_most_edited = Mock()
        mock_most_edited.file_path = "server.properties"
        mock_most_edited.version_count = 8

        # Set up query chain
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.side_effect = [mock_stats, mock_most_edited]
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query

        result = await service.get_server_statistics(server_id=1, db=mock_db)

        assert result["server_id"] == 1
        assert result["total_files_with_history"] == 5
        assert result["total_versions"] == 15
        assert result["total_storage_used"] == 102400
        assert result["most_edited_file"] == "server.properties"
        assert result["most_edited_file_versions"] == 8

    @pytest.mark.asyncio
    async def test_get_server_statistics_no_data(self, service, mock_db):
        """Test server statistics with no data"""
        mock_stats = Mock()
        mock_stats.total_files = None
        mock_stats.total_versions = None
        mock_stats.total_storage = None
        mock_stats.oldest_version = None
        mock_stats.newest_version = None

        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.side_effect = [mock_stats, None]
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query

        result = await service.get_server_statistics(server_id=1, db=mock_db)

        assert result["total_files_with_history"] == 0
        assert result["total_versions"] == 0
        assert result["total_storage_used"] == 0
        assert result["most_edited_file"] is None
        assert result["most_edited_file_versions"] is None

    # Test cleanup_old_versions method (lines 299-338)
    @pytest.mark.asyncio
    async def test_cleanup_old_versions_success(self, service, mock_db):
        """Test successful cleanup of old versions"""
        # Create mock old records
        mock_record1 = Mock(spec=FileEditHistory)
        mock_record1.backup_file_path = "/tmp/backup1.txt"
        mock_record1.file_size = 1024

        mock_record2 = Mock(spec=FileEditHistory)
        mock_record2.backup_file_path = "/tmp/backup2.txt"
        mock_record2.file_size = 2048

        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_record1, mock_record2]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 1024
                with patch("pathlib.Path.unlink"):
                    result = await service.cleanup_old_versions(days=30, db=mock_db)

                    assert isinstance(result, CleanupResult)
                    assert result.deleted_versions == 2
                    assert result.freed_storage == 2048  # 2 calls * 1024 each
                    assert result.cleanup_type == "older_than_30_days"
                    mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_old_versions_with_server_filter(self, service, mock_db):
        """Test cleanup with server filter"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        await service.cleanup_old_versions(days=15, server_id=1, db=mock_db)

        # Verify server filter was applied (2 filter calls: date and server_id)
        assert mock_query.filter.call_count == 2

    @pytest.mark.asyncio
    async def test_cleanup_old_versions_no_files_to_delete(self, service, mock_db):
        """Test cleanup when no files need deletion"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        result = await service.cleanup_old_versions(db=mock_db)

        assert result.deleted_versions == 0
        assert result.freed_storage == 0
        assert result.cleanup_type == "older_than_30_days"

    @pytest.mark.asyncio
    async def test_cleanup_old_versions_file_not_exists(self, service, mock_db):
        """Test cleanup when backup files don't exist"""
        mock_record = Mock(spec=FileEditHistory)
        mock_record.backup_file_path = "/tmp/nonexistent.txt"

        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_record]

        with patch("pathlib.Path.exists", return_value=False):
            result = await service.cleanup_old_versions(db=mock_db)

            assert result.deleted_versions == 1
            assert result.freed_storage == 0  # No file to delete
            mock_db.delete.assert_called_with(mock_record)

    # Test _normalize_file_path method (lines 340-343)
    def test_normalize_file_path(self, service):
        """Test file path normalization"""
        assert service._normalize_file_path("/test/path.txt") == "test/path.txt"
        assert service._normalize_file_path("//test//path.txt") == "test/path.txt"
        assert service._normalize_file_path("test/path.txt") == "test/path.txt"
        assert service._normalize_file_path("") == "."

    # Test _get_next_version_number method (lines 345-358)
    @pytest.mark.asyncio
    async def test_get_next_version_number_first_version(self, service, mock_db):
        """Test getting first version number"""
        mock_db.query.return_value.filter.return_value.scalar.return_value = None

        result = await service._get_next_version_number(1, "test.txt", mock_db)
        assert result == 1

    @pytest.mark.asyncio
    async def test_get_next_version_number_increment(self, service, mock_db):
        """Test incrementing version number"""
        mock_db.query.return_value.filter.return_value.scalar.return_value = 5

        result = await service._get_next_version_number(1, "test.txt", mock_db)
        assert result == 6

    # Test _is_duplicate_content method (lines 360-374)
    @pytest.mark.asyncio
    async def test_is_duplicate_content_true(self, service, mock_db):
        """Test duplicate content detection returns True"""
        mock_record = Mock()
        mock_record.content_hash = "abcd1234"

        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = mock_record

        result = await service._is_duplicate_content(1, "test.txt", "abcd1234", mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_duplicate_content_false_different_hash(self, service, mock_db):
        """Test duplicate content detection returns False for different hash"""
        mock_record = Mock()
        mock_record.content_hash = "different1234"

        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = mock_record

        result = await service._is_duplicate_content(1, "test.txt", "abcd1234", mock_db)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_duplicate_content_false_no_record(self, service, mock_db):
        """Test duplicate content detection returns falsy when no record exists"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = None

        result = await service._is_duplicate_content(1, "test.txt", "abcd1234", mock_db)
        assert not result  # Result is falsy (None) when no record exists

    # Test _cleanup_excess_versions method (lines 376-404)
    @pytest.mark.asyncio
    async def test_cleanup_excess_versions_success(self, service, mock_db):
        """Test successful cleanup of excess versions"""
        mock_record1 = Mock()
        mock_record1.backup_file_path = "/tmp/old1.txt"
        mock_record2 = Mock()
        mock_record2.backup_file_path = "/tmp/old2.txt"

        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = [mock_record1, mock_record2]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.unlink") as mock_unlink:
                await service._cleanup_excess_versions(1, "test.txt", mock_db)

                assert mock_unlink.call_count == 2
                assert mock_db.delete.call_count == 2
                mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_excess_versions_no_excess(self, service, mock_db):
        """Test cleanup when no excess versions exist"""
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = []

        await service._cleanup_excess_versions(1, "test.txt", mock_db)

        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_excess_versions_file_not_exists(self, service, mock_db):
        """Test cleanup when backup file doesn't exist"""
        mock_record = Mock()
        mock_record.backup_file_path = "/tmp/nonexistent.txt"

        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = [mock_record]

        with patch("pathlib.Path.exists", return_value=False):
            await service._cleanup_excess_versions(1, "test.txt", mock_db)

            mock_db.delete.assert_called_with(mock_record)
            mock_db.commit.assert_called_once()

    # Test _to_record_schema method (lines 406-425)
    def test_to_record_schema_with_editor(self, service, mock_db):
        """Test converting record to schema with editor"""
        record = Mock(spec=FileEditHistory)
        record.id = 1
        record.server_id = 1
        record.file_path = "test.txt"
        record.version_number = 1
        record.backup_file_path = "/tmp/backup/file.txt"
        record.file_size = 1024
        record.content_hash = "abcd1234"
        record.editor_user_id = 1
        record.created_at = datetime.now()
        record.description = "Test record"
        record.editor = Mock()
        record.editor.username = "testuser"

        result = service._to_record_schema(record, mock_db)

        assert isinstance(result, FileHistoryRecord)
        assert result.id == 1
        assert result.server_id == 1
        assert result.file_path == "test.txt"
        assert result.editor_username == "testuser"

    def test_to_record_schema_without_editor(self, service, mock_db):
        """Test converting record to schema without editor"""
        record = Mock(spec=FileEditHistory)
        record.id = 1
        record.server_id = 1
        record.file_path = "test.txt"
        record.version_number = 1
        record.backup_file_path = "/tmp/backup/file.txt"
        record.file_size = 1024
        record.content_hash = "abcd1234"
        record.editor_user_id = None
        record.created_at = datetime.now()
        record.description = None
        record.editor = None

        result = service._to_record_schema(record, mock_db)

        assert isinstance(result, FileHistoryRecord)
        assert result.editor_username is None
        assert result.description is None


class TestFileHistoryServiceInitialization:
    """Test service initialization and configuration"""

    def test_service_initialization(self):
        """Test FileHistoryService initialization"""
        service = FileHistoryService()

        assert service.history_base_dir == Path("./file_history")
        assert service.max_versions_per_file == 50
        assert service.auto_cleanup_days == 30

    def test_service_singleton_instance(self):
        """Test that file_history_service instance is available"""
        assert file_history_service is not None
        assert isinstance(file_history_service, FileHistoryService)


class TestFileHistoryServiceErrorHandling:
    """Test comprehensive error handling scenarios"""

    @pytest.fixture
    def service(self):
        return FileHistoryService()

    @pytest.fixture
    def mock_db(self):
        return Mock(spec=Session)

    @pytest.mark.asyncio
    async def test_various_file_operation_errors(self, service, mock_db):
        """Test various file operation error scenarios"""
        # Test directory creation error
        with patch.object(service, "_normalize_file_path", return_value="test.txt"):
            with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
                with pytest.raises(FileOperationException):
                    await service.create_version_backup(
                        server_id=1, file_path="test.txt", content="test", db=mock_db
                    )

    @pytest.mark.asyncio
    async def test_database_operation_errors(self, service, mock_db):
        """Test database operation error scenarios"""
        # Test database commit error
        mock_db.commit.side_effect = Exception("Database error")

        with patch.object(service, "_normalize_file_path", return_value="test.txt"):
            with patch("pathlib.Path.mkdir"):
                with patch.object(service, "_is_duplicate_content", return_value=False):
                    with patch.object(
                        service, "_get_next_version_number", return_value=1
                    ):
                        with patch("aiofiles.open", mock_open()):
                            with pytest.raises(FileOperationException):
                                await service.create_version_backup(
                                    server_id=1,
                                    file_path="test.txt",
                                    content="test",
                                    db=mock_db,
                                )

    def test_edge_case_file_paths(self, service):
        """Test edge case file paths in normalization"""
        # Test various edge cases - these are based on what Path().lstrip("/") actually does
        assert service._normalize_file_path("///") == "."
        assert service._normalize_file_path("/test/file.txt") == "test/file.txt"
        assert service._normalize_file_path("test/file.txt") == "test/file.txt"


class TestFileHistoryServiceIntegration:
    """Integration tests for realistic scenarios"""

    @pytest.fixture
    def service(self):
        return FileHistoryService()

    @pytest.mark.asyncio
    async def test_complete_file_lifecycle(self, service):
        """Test complete file history lifecycle"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock database session
            mock_db = Mock(spec=Session)

            # Mock all database operations
            mock_db.query.return_value.filter.return_value.scalar.return_value = (
                None  # First version
            )
            mock_db.add = Mock()
            mock_db.commit = Mock()
            mock_db.refresh = Mock()

            # Mock the cleanup method to avoid database calls
            with patch.object(service, "_cleanup_excess_versions"):
                with patch.object(service, "_to_record_schema") as mock_schema:
                    mock_schema.return_value = FileHistoryRecord(
                        id=1,
                        server_id=1,
                        file_path="test.txt",
                        version_number=1,
                        backup_file_path="/tmp/backup/file.txt",
                        file_size=12,
                        content_hash="hash",
                        editor_user_id=1,
                        editor_username="test",
                        created_at=datetime.now(),
                        description="test",
                    )

                    # Set service history directory to temp directory
                    service.history_base_dir = Path(temp_dir)

                    # Test creating a backup
                    result = await service.create_version_backup(
                        server_id=1,
                        file_path="test.txt",
                        content="test content",
                        user_id=1,
                        description="Test backup",
                        db=mock_db,
                    )

                    assert result is not None
                    assert result.version_number == 1

    @pytest.mark.asyncio
    async def test_multiple_versions_scenario(self, service):
        """Test scenario with multiple versions of the same file"""
        mock_db = Mock(spec=Session)

        # Mock version number progression
        version_numbers = [None, 1, 2]  # None -> 1, 1 -> 2, 2 -> 3
        mock_db.query.return_value.filter.return_value.scalar.side_effect = (
            version_numbers
        )

        # Mock duplicate content checks (always False for this test)
        with patch.object(service, "_is_duplicate_content", return_value=False):
            with patch.object(service, "_cleanup_excess_versions"):
                with patch("pathlib.Path.mkdir"):
                    mock_file = AsyncMock()
                    mock_file.write = AsyncMock()
                    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
                    mock_file.__aexit__ = AsyncMock(return_value=None)
                    with patch("aiofiles.open", return_value=mock_file):
                        with patch.object(service, "_to_record_schema") as mock_schema:
                            mock_schema.side_effect = [
                                FileHistoryRecord(
                                    id=1,
                                    server_id=1,
                                    file_path="test.txt",
                                    version_number=1,
                                    backup_file_path="/tmp/backup/file.txt",
                                    file_size=10,
                                    content_hash="hash1",
                                    editor_user_id=1,
                                    editor_username="test",
                                    created_at=datetime.now(),
                                    description="v1",
                                ),
                                FileHistoryRecord(
                                    id=2,
                                    server_id=1,
                                    file_path="test.txt",
                                    version_number=2,
                                    backup_file_path="/tmp/backup/file.txt",
                                    file_size=10,
                                    content_hash="hash2",
                                    editor_user_id=1,
                                    editor_username="test",
                                    created_at=datetime.now(),
                                    description="v2",
                                ),
                                FileHistoryRecord(
                                    id=3,
                                    server_id=1,
                                    file_path="test.txt",
                                    version_number=3,
                                    backup_file_path="/tmp/backup/file.txt",
                                    file_size=10,
                                    content_hash="hash3",
                                    editor_user_id=1,
                                    editor_username="test",
                                    created_at=datetime.now(),
                                    description="v3",
                                ),
                            ]

                            # Create three versions
                            v1 = await service.create_version_backup(
                                1, "test.txt", "content1", 1, "v1", mock_db
                            )
                            v2 = await service.create_version_backup(
                                1, "test.txt", "content2", 1, "v2", mock_db
                            )
                            v3 = await service.create_version_backup(
                                1, "test.txt", "content3", 1, "v3", mock_db
                            )

                            assert v1.version_number == 1
                            assert v2.version_number == 2
                            assert v3.version_number == 3
