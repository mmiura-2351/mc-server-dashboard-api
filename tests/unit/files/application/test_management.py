from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import UploadFile

from app.core.exceptions import (
    AccessDeniedException,
    FileOperationException,
    InvalidRequestException,
    ServerNotFoundException,
)
from app.files.application.management import file_management_service
from app.servers.models import Server
from app.users.domain.value_objects import Role
from app.users.models import User


class TestFileManagementService:
    @pytest.fixture
    def mock_server(self):
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test_server"
        server.directory_path = "servers/test_server"
        return server

    @pytest.fixture
    def mock_user(self):
        user = Mock(spec=User)
        user.id = 1
        user.username = "testuser"
        user.role = Role.user
        return user

    @pytest.fixture
    def mock_admin_user(self):
        user = Mock(spec=User)
        user.id = 2
        user.username = "admin"
        user.role = Role.admin
        return user

    @pytest.fixture
    def mock_db(self):
        return Mock()

    @pytest.mark.asyncio
    async def test_get_server_files_server_not_found(self, mock_db):
        """Test get_server_files when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None

        with pytest.raises(ServerNotFoundException):
            await file_management_service.get_server_files(server_id=999, db=mock_db)

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    async def test_get_server_files_directory_not_found(
        self, mock_exists, mock_server, mock_db
    ):
        """Test get_server_files when server directory doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = False

        with pytest.raises(FileOperationException):
            await file_management_service.get_server_files(server_id=1, db=mock_db)

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    async def test_get_server_files_path_traversal(
        self, mock_exists, mock_server, mock_db
    ):
        """Test get_server_files with path traversal attempt"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.side_effect = [True, True]  # server_path and target_path exist

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/etc/passwd"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]

            with pytest.raises(AccessDeniedException):
                await file_management_service.get_server_files(
                    server_id=1, path="../../../etc/passwd", db=mock_db
                )

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    @patch("pathlib.Path.iterdir")
    async def test_get_server_files_directory_success(
        self, mock_iterdir, mock_is_dir, mock_exists, mock_server, mock_db
    ):
        """Test successful directory listing"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        mock_file = Mock()
        mock_file.name = "test.txt"
        mock_file.stat.return_value.st_size = 1024
        mock_file.stat.return_value.st_mtime = 1640995200
        mock_file.is_dir.return_value = False
        mock_file.is_file.return_value = True
        mock_file.suffix = ".txt"
        mock_file.relative_to.return_value = Path("test.txt")

        mock_iterdir.return_value = [mock_file]

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]

            result = await file_management_service.get_server_files(
                server_id=1, db=mock_db
            )

            assert len(result) == 1
            assert result[0]["name"] == "test.txt"

    @pytest.mark.asyncio
    async def test_read_file_server_not_found(self, mock_db):
        """Test read_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None

        with pytest.raises(ServerNotFoundException):
            await file_management_service.read_file(
                server_id=999, file_path="test.txt", db=mock_db
            )

    @pytest.mark.asyncio
    async def test_read_file_path_traversal(self, mock_server, mock_db):
        """Test read_file with path traversal attempt"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/etc/passwd"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]

            with pytest.raises(AccessDeniedException):
                await file_management_service.read_file(
                    server_id=1, file_path="../../../etc/passwd", db=mock_db
                )

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    async def test_read_file_not_found(self, mock_exists, mock_server, mock_db):
        """Test read_file when file doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = False

        with pytest.raises(FileOperationException):
            await file_management_service.read_file(
                server_id=1, file_path="nonexistent.txt", db=mock_db
            )

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    async def test_read_file_is_directory(
        self, mock_is_dir, mock_exists, mock_server, mock_db
    ):
        """Test read_file when target is a directory"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/directory"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]

            with pytest.raises(FileOperationException):
                await file_management_service.read_file(
                    server_id=1, file_path="directory", db=mock_db
                )

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    @patch("app.files.application.management.EncodingHandler.safe_read_text_file")
    async def test_read_file_success(
        self, mock_safe_read, mock_is_dir, mock_exists, mock_server, mock_db
    ):
        """Test successful file read"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = True
        mock_is_dir.return_value = False

        # Mock encoding handler to return success
        mock_safe_read.return_value = {
            "success": True,
            "content": "file content",
            "encoding": "utf-8",
            "error": None,
        }

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]
            with patch("pathlib.Path.suffix", ".txt"):
                result = await file_management_service.read_file(
                    server_id=1, file_path="test.txt", db=mock_db
                )

                # Result should be a tuple (content, encoding)
                assert result[0] == "file content"  # content
                assert result[1] == "utf-8"  # encoding

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    @patch("app.files.application.management.EncodingHandler.safe_read_text_file")
    async def test_read_file_unicode_error(
        self, mock_safe_read, mock_is_dir, mock_exists, mock_server, mock_db
    ):
        """Test read_file with unicode decode error"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = True
        mock_is_dir.return_value = False

        # Mock encoding handler to return failure
        mock_safe_read.return_value = {
            "success": False,
            "content": "",
            "encoding": None,
            "error": "Unable to decode file with any encoding",
        }

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/binary.txt"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]
            with patch("pathlib.Path.suffix", ".txt"):
                with pytest.raises(FileOperationException):
                    await file_management_service.read_file(
                        server_id=1, file_path="binary.txt", db=mock_db
                    )

    @pytest.mark.asyncio
    async def test_write_file_server_not_found(self, mock_db):
        """Test write_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None

        with pytest.raises(ServerNotFoundException):
            await file_management_service.write_file(
                server_id=999, file_path="test.txt", content="content", db=mock_db
            )

    @pytest.mark.asyncio
    @patch("pathlib.Path.resolve")
    async def test_write_file_path_traversal(
        self, mock_resolve, mock_server, mock_user, mock_db
    ):
        """Test write_file with path traversal attempt"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_resolve.side_effect = [
            Path("/etc/passwd"),  # target_path.resolve()
            Path("/servers/test_server"),  # server_path.resolve()
        ]

        with pytest.raises(AccessDeniedException):
            await file_management_service.write_file(
                server_id=1,
                file_path="../../../etc/passwd",
                content="content",
                user=mock_user,
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_write_file_restricted_non_admin(self, mock_server, mock_user, mock_db):
        """Test write_file restricted file by non-admin user"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/ops.json"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]
            with patch("pathlib.Path.name", "ops.json"):
                with pytest.raises(AccessDeniedException):
                    await file_management_service.write_file(
                        server_id=1,
                        file_path="ops.json",
                        content="[]",
                        user=mock_user,
                        db=mock_db,
                    )

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("aiofiles.open")
    async def test_write_file_success(
        self, mock_aiofiles_open, mock_exists, mock_server, mock_user, mock_db
    ):
        """Test successful file write"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = False

        mock_file = AsyncMock()
        mock_aiofiles_open.return_value.__aenter__.return_value = mock_file

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]
            with patch("pathlib.Path.suffix", ".txt"):
                with patch("pathlib.Path.name", "test.txt"):
                    with patch("pathlib.Path.mkdir"):
                        with patch("pathlib.Path.stat") as mock_stat:
                            mock_stat.return_value.st_size = 7
                            mock_stat.return_value.st_mtime = 1640995200
                            with patch("pathlib.Path.is_dir", return_value=False):
                                with patch("pathlib.Path.is_file", return_value=True):
                                    with patch(
                                        "pathlib.Path.relative_to",
                                        return_value=Path("test.txt"),
                                    ):
                                        result = await file_management_service.write_file(
                                            server_id=1,
                                            file_path="test.txt",
                                            content="content",
                                            user=mock_user,
                                            db=mock_db,
                                        )

                                    assert "updated successfully" in result["message"]
                                    assert result["file"]["name"] == "test.txt"
                                    mock_file.write.assert_called_once_with("content")

    @pytest.mark.asyncio
    async def test_delete_file_server_not_found(self, mock_db):
        """Test delete_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None

        with pytest.raises(ServerNotFoundException):
            await file_management_service.delete_file(
                server_id=999, file_path="test.txt", db=mock_db
            )

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    async def test_delete_file_not_found(
        self, mock_exists, mock_server, mock_user, mock_db
    ):
        """Test delete_file when file doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = False

        with pytest.raises(FileOperationException):
            await file_management_service.delete_file(
                server_id=1, file_path="nonexistent.txt", user=mock_user, db=mock_db
            )

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.unlink")
    async def test_delete_file_success(
        self,
        mock_unlink,
        mock_is_file,
        mock_exists,
        mock_server,
        mock_admin_user,
        mock_db,
    ):
        """Test successful file deletion"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = True
        mock_is_file.return_value = True

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]
            with patch("pathlib.Path.suffix", ".txt"):
                with patch("pathlib.Path.name", "test.txt"):
                    with patch("pathlib.Path.is_dir", return_value=False):
                        result = await file_management_service.delete_file(
                            server_id=1,
                            file_path="test.txt",
                            user=mock_admin_user,
                            db=mock_db,
                        )

                        assert "deleted successfully" in result["message"]
                        mock_unlink.assert_called_once()

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    @patch("shutil.rmtree")
    async def test_delete_directory_success(
        self, mock_rmtree, mock_is_dir, mock_exists, mock_server, mock_admin_user, mock_db
    ):
        """Test successful directory deletion"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test_dir"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]
            with patch("pathlib.Path.is_file", return_value=False):
                with patch("pathlib.Path.name", "test_dir"):
                    result = await file_management_service.delete_file(
                        server_id=1,
                        file_path="test_dir",
                        user=mock_admin_user,
                        db=mock_db,
                    )

                    assert "Directory" in result["message"]
                    assert "deleted successfully" in result["message"]
                    mock_rmtree.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_file_server_not_found(self, mock_db):
        """Test upload_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None

        mock_file = Mock(spec=UploadFile)
        mock_file.filename = "test.txt"

        with pytest.raises(ServerNotFoundException):
            await file_management_service.upload_file(
                server_id=999, file=mock_file, db=mock_db
            )

    @pytest.mark.asyncio
    @patch("aiofiles.open")
    async def test_upload_file_success(
        self, mock_aiofiles_open, mock_server, mock_user, mock_db
    ):
        """Test successful file upload"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )

        mock_file = Mock(spec=UploadFile)
        mock_file.filename = "test.txt"
        # Chunked upload (#341): first read returns the payload, the
        # next signals EOF so the streaming loop terminates.
        mock_file.read = AsyncMock(side_effect=[b"file content", b""])

        mock_aio_file = AsyncMock()
        mock_aiofiles_open.return_value.__aenter__.return_value = mock_aio_file

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server"),  # target_dir.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
                Path("/servers/test_server/test.txt"),  # target_file.resolve()
                Path("/servers/test_server"),  # server_path.resolve() (2nd check)
            ]

            # Mock all file system operations
            with patch("pathlib.Path.mkdir"):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 12  # len(b"file content")
                    mock_stat.return_value.st_mtime = 1640995200
                    with patch("pathlib.Path.is_dir", return_value=False):
                        with patch("pathlib.Path.is_file", return_value=True):
                            with patch("pathlib.Path.suffix", ".txt"):
                                with patch(
                                    "pathlib.Path.relative_to",
                                    return_value=Path("test.txt"),
                                ):
                                    with patch("pathlib.Path.name", "test.txt"):
                                        result = (
                                            await file_management_service.upload_file(
                                                server_id=1, file=mock_file, db=mock_db
                                            )
                                        )

            assert "uploaded successfully" in result["message"]
            assert result["file"]["name"] == "test.txt"
            assert result["extracted_files"] == []
            mock_aio_file.write.assert_called_once_with(b"file content")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("bad_name", "expected_exc"),
        [
            (None, InvalidRequestException),
            ("", InvalidRequestException),
            (".", InvalidRequestException),
            ("..", AccessDeniedException),
        ],
    )
    async def test_upload_file_rejects_missing_or_empty_filename(
        self, mock_server, mock_db, tmp_path, bad_name, expected_exc
    ):
        """``UploadFile.filename`` is ``Optional[str]``; reject missing or
        directory-only inputs (``Path(".").name == ""``) before they reach
        ``Path(None)`` (TypeError) or land on ``target_dir`` itself.
        ``".."`` passes the empty check but is caught by ``validate_path_safety``."""
        server_dir = tmp_path / "test_server"
        server_dir.mkdir()
        mock_server.directory_path = str(server_dir)
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )

        mock_file = Mock(spec=UploadFile)
        mock_file.filename = bad_name

        with pytest.raises(expected_exc):
            await file_management_service.upload_file(
                server_id=1, file=mock_file, db=mock_db
            )

    @pytest.mark.asyncio
    async def test_upload_file_strips_traversal_in_filename(
        self, mock_server, mock_db, tmp_path
    ):
        """Regression for #400: traversal sequences in ``file.filename`` must
        not escape the server directory."""
        server_dir = tmp_path / "test_server"
        server_dir.mkdir()
        mock_server.directory_path = str(server_dir)
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )

        mock_file = Mock(spec=UploadFile)
        mock_file.filename = "../../evil.txt"

        captured: dict = {}

        async def _capture_upload(upload, target_path):
            captured["target"] = target_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"x")
            return 1

        with patch.object(
            file_management_service.operation_service,
            "upload_file",
            side_effect=_capture_upload,
        ):
            result = await file_management_service.upload_file(
                server_id=1, file=mock_file, db=mock_db
            )

        # File was written inside server_dir (basename only), not outside.
        assert captured["target"].parent.resolve() == server_dir.resolve()
        assert captured["target"].name == "evil.txt"
        assert not (tmp_path / "evil.txt").exists()
        assert result["file"]["name"] == "evil.txt"
        assert "evil.txt" in result["message"]

    @pytest.mark.asyncio
    async def test_download_file_server_not_found(self, mock_db):
        """Test download_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None

        with pytest.raises(ServerNotFoundException):
            await file_management_service.download_file(
                server_id=999, file_path="test.txt", db=mock_db
            )

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    async def test_download_file_success(
        self, mock_is_dir, mock_exists, mock_server, mock_db
    ):
        """Test successful file download"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = True
        mock_is_dir.return_value = False

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]
            with patch("pathlib.Path.suffix", ".txt"):
                with patch("pathlib.Path.name", "test.txt"):
                    result = await file_management_service.download_file(
                        server_id=1, file_path="test.txt", db=mock_db
                    )

                    _, filename = result
                    assert filename == "test.txt"

    @pytest.mark.asyncio
    async def test_create_directory_server_not_found(self, mock_db):
        """Test create_directory when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None

        with pytest.raises(ServerNotFoundException):
            await file_management_service.create_directory(
                server_id=999, directory_path="testdir", db=mock_db
            )

    @pytest.mark.asyncio
    async def test_create_directory_success(self, mock_server, mock_db):
        """Test successful directory creation"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/newdir"),  # target_dir.resolve()
                Path("/servers/test_server"),  # server_path.resolve()
            ]
            with patch("pathlib.Path.mkdir") as mock_mkdir:
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 0
                    mock_stat.return_value.st_mtime = 1640995200.0
                    with patch("pathlib.Path.is_dir", return_value=True):
                        with patch("pathlib.Path.is_file", return_value=False):
                            result = await file_management_service.create_directory(
                                server_id=1, directory_path="newdir", db=mock_db
                            )

                            assert "created successfully" in result["message"]
                            mock_mkdir.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_files_server_not_found(self, mock_db):
        """Test search_files when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None

        with pytest.raises(ServerNotFoundException):
            await file_management_service.search_files(
                server_id=999, search_term="test", db=mock_db
            )

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.rglob")
    async def test_search_files_success(
        self, mock_rglob, mock_exists, mock_server, mock_db
    ):
        """Test successful file search"""
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_server
        )
        mock_exists.return_value = True

        mock_file = Mock()
        mock_file.name = "server.properties"
        mock_file.stat.return_value.st_size = 1024
        mock_file.stat.return_value.st_mtime = 1640995200
        mock_file.is_dir.return_value = False
        mock_file.is_file.return_value = True
        mock_file.suffix = ".properties"
        mock_file.relative_to.return_value = Path("server.properties")

        mock_rglob.return_value = [mock_file]

        result = await file_management_service.search_files(
            server_id=1, search_term="server", db=mock_db
        )

        assert result["search_term"] == "server"
        assert result["total_found"] >= 0
        assert "search_time_seconds" in result

    def test_file_validation_service_init(self):
        """Test FileValidationService initialization"""
        service = file_management_service.validation_service
        assert service.allowed_extensions is not None
        assert service.restricted_files is not None
        assert "server.jar" in service.restricted_files
        assert "eula.txt" in service.restricted_files

    def test_is_safe_path_valid(self):
        """Test _is_safe_path with valid path"""
        service = file_management_service.validation_service

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test/subdir/file.txt"),  # target.resolve()
                Path("/servers/test"),  # base.resolve()
            ]

            result = service._is_safe_path(
                Path("/servers/test"), Path("/servers/test/subdir/file.txt")
            )
            assert result

    def test_is_safe_path_invalid(self):
        """Test _is_safe_path with invalid path traversal"""
        service = file_management_service.validation_service

        with patch("pathlib.Path.resolve") as mock_resolve:
            # Mock the relative_to method to raise ValueError for path traversal
            mock_target_resolved = Mock()
            mock_base_resolved = Mock()
            mock_target_resolved.relative_to.side_effect = ValueError("Path traversal")

            mock_resolve.side_effect = [mock_target_resolved, mock_base_resolved]

            result = service._is_safe_path(
                Path("/servers/test"), Path("/servers/test/../../../etc/passwd")
            )
            assert not result

    def test_is_readable_file_allowed_extension(self):
        """Test _is_readable_file with allowed extension"""
        service = file_management_service.validation_service

        result = service._is_readable_file(Path("test.txt"))
        assert result

    def test_is_readable_file_config_extension(self):
        """Test _is_readable_file with config extension"""
        service = file_management_service.validation_service

        result = service._is_readable_file(Path("server.properties"))
        assert result

    def test_is_writable_file_allowed(self):
        """Test _is_writable_file with allowed extension"""
        service = file_management_service.validation_service

        with patch("pathlib.Path.is_dir", return_value=False):
            result = service._is_writable_file(Path("test.txt"))
            assert result

    def test_is_writable_file_not_allowed(self):
        """Test _is_writable_file with not allowed extension"""
        service = file_management_service.validation_service

        with patch("pathlib.Path.is_dir", return_value=False):
            result = service._is_writable_file(Path("test.jar"))
            assert not result

    def test_is_writable_file_directory(self):
        """Test _is_writable_file with directory"""
        service = file_management_service.validation_service

        with patch("pathlib.Path.is_dir", return_value=True):
            result = service._is_writable_file(Path("testdir"))
            assert not result

    def test_is_restricted_file(self):
        """Test _is_restricted_file"""
        service = file_management_service.validation_service

        result = service._is_restricted_file(Path("ops.json"))
        assert result

        result = service._is_restricted_file(Path("test.txt"))
        assert not result

    def test_enhanced_restricted_files_list(self):
        """Test that all critical Minecraft server files are properly restricted"""
        service = file_management_service.validation_service

        # Original restricted files (should still be protected)
        original_restricted = [
            "server.jar",
            "eula.txt",
            "ops.json",
            "whitelist.json",
            "banned-players.json",
            "banned-ips.json",
        ]

        # Newly added critical files (enhanced security)
        new_restricted = [
            # Server configuration files
            "bukkit.yml",
            "spigot.yml",
            "paper.yml",
            "paper-global.yml",
            "paper-world-defaults.yml",
            # Plugin and command configuration
            "plugins.yml",
            "commands.yml",
            "permissions.yml",
            "help.yml",
            # World data files
            "level.dat",
            "level.dat_old",
            "session.lock",
            # User cache and security files
            "usercache.json",
            "usernamecache.json",
            # Additional server JARs
            "minecraft_server.jar",
            "forge.jar",
            "fabric-server-launch.jar",
            # Plugin management
            "plugin.yml",
            "mod.toml",
            # Proxy configurations
            "config.yml",
            "velocity.toml",
            "waterfall.yml",
        ]

        # Test all original files are still protected
        for filename in original_restricted:
            assert service._is_restricted_file(Path(filename)), (
                f"Original restricted file {filename} should be protected"
            )

        # Test all new files are now protected
        for filename in new_restricted:
            assert service._is_restricted_file(Path(filename)), (
                f"New restricted file {filename} should be protected"
            )

        # Test that non-restricted files are not protected
        non_restricted = [
            "README.txt",
            "notes.md",
            "custom-config.yml",
            "logs/latest.log",
            "plugins/CustomPlugin.jar",
        ]
        for filename in non_restricted:
            assert not service._is_restricted_file(Path(filename)), (
                f"Non-restricted file {filename} should not be protected"
            )


class TestUploadFileOperation:
    """Issue #341: upload_file streams the payload and rejects oversize uploads."""

    @pytest.mark.asyncio
    async def test_upload_file_streams_chunked_reads(self, tmp_path):
        """upload_file consumes the file with bounded ``read(N)`` calls."""
        from app.files.application.management import FileOperationService

        service = FileOperationService(backup_service=Mock())
        target = tmp_path / "uploaded.bin"

        payload = b"abcdef" * 1000  # 6 KiB — fits in a single 64 KiB chunk
        chunks = [payload, b""]
        mock_file = Mock(spec=UploadFile)
        mock_file.read = AsyncMock(side_effect=chunks)

        written = await service.upload_file(mock_file, target)

        assert written == len(payload)
        assert target.read_bytes() == payload
        # First call requested at most CHUNK_BYTES; second call drains EOF.
        assert mock_file.read.call_args_list[0].args[0] == service._UPLOAD_CHUNK_BYTES

    @pytest.mark.asyncio
    async def test_upload_file_rejects_oversize(self, tmp_path, monkeypatch):
        """Exceeding ``FILE_MAX_UPLOAD_BYTES`` raises ``FileTooLargeError``."""
        from app.core.exceptions import FileTooLargeError
        from app.files.application.management import FileOperationService, settings

        monkeypatch.setattr(settings, "FILE_MAX_UPLOAD_BYTES", 128)

        service = FileOperationService(backup_service=Mock())
        target = tmp_path / "huge.bin"

        # 64 KiB chunk * 3 => 192 KiB, well over the 128-byte cap.
        oversize = b"x" * (64 * 1024)
        mock_file = Mock(spec=UploadFile)
        mock_file.read = AsyncMock(side_effect=[oversize, oversize, b""])

        with pytest.raises(FileTooLargeError) as excinfo:
            await service.upload_file(mock_file, target)

        # The error carries the running size + configured cap and the
        # partial output is cleaned up so storage isn't leaked.
        assert excinfo.value.size_bytes is not None
        assert excinfo.value.size_bytes > 128
        assert excinfo.value.max_bytes == 128
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_upload_file_limit_zero_disables_enforcement(
        self, tmp_path, monkeypatch
    ):
        """``FILE_MAX_UPLOAD_BYTES = 0`` allows arbitrarily large uploads."""
        from app.files.application.management import FileOperationService, settings

        monkeypatch.setattr(settings, "FILE_MAX_UPLOAD_BYTES", 0)

        service = FileOperationService(backup_service=Mock())
        target = tmp_path / "unbounded.bin"
        big = b"y" * (64 * 1024)
        mock_file = Mock(spec=UploadFile)
        mock_file.read = AsyncMock(side_effect=[big, big, b""])

        written = await service.upload_file(mock_file, target)
        assert written == 2 * len(big)
        assert target.stat().st_size == 2 * len(big)


class TestRenameFileAlreadyExists:
    """Issue #341: rename surfaces 409 ``FileAlreadyExistsError`` on conflict."""

    @pytest.mark.asyncio
    async def test_rename_conflict_raises_file_already_exists(self, tmp_path):
        from app.core.exceptions import FileAlreadyExistsError
        from app.files.application.management import file_management_service

        # Stage a real server directory with both the source and the
        # conflicting destination already present.
        server_dir = tmp_path / "srv"
        server_dir.mkdir()
        (server_dir / "src.txt").write_text("hello")
        (server_dir / "dst.txt").write_text("collision")

        server = Mock(spec=Server)
        server.id = 1
        server.directory_path = str(server_dir)

        mock_db = Mock()
        user = Mock(spec=User)
        user.id = 1
        user.username = "operator"
        user.role = Role.admin

        with patch.object(
            file_management_service.validation_service,
            "validate_server_exists",
            new=AsyncMock(return_value=server),
        ):
            with pytest.raises(FileAlreadyExistsError) as excinfo:
                await file_management_service.rename_file(
                    server_id=1,
                    file_path="src.txt",
                    new_name="dst.txt",
                    db=mock_db,
                    user=user,
                )

        # The error envelope carries the conflicting path so the UI can
        # offer "rename to" / "delete first" without an extra round-trip.
        assert excinfo.value.existing_path == "dst.txt"
        assert excinfo.value.status_code == 409
