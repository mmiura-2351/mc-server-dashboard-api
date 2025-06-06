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
from app.servers.models import Server
from app.services.file_management_service import file_management_service
from app.users.models import Role, User


class TestFileManagementService:
    
    @pytest.fixture
    def mock_server(self):
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test_server"
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
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(ServerNotFoundException):
            await file_management_service.get_server_files(server_id=999, db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    async def test_get_server_files_directory_not_found(self, mock_exists, mock_server, mock_db):
        """Test get_server_files when server directory doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = False
        
        with pytest.raises(FileOperationException):
            await file_management_service.get_server_files(server_id=1, db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    async def test_get_server_files_path_traversal(self, mock_exists, mock_server, mock_db):
        """Test get_server_files with path traversal attempt"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.side_effect = [True, True]  # server_path and target_path exist
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/etc/passwd"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            
            with pytest.raises(AccessDeniedException):
                await file_management_service.get_server_files(
                    server_id=1, path="../../../etc/passwd", db=mock_db
                )

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('pathlib.Path.iterdir')
    async def test_get_server_files_directory_success(self, mock_iterdir, mock_is_dir, mock_exists, mock_server, mock_db):
        """Test successful directory listing"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
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
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            
            result = await file_management_service.get_server_files(server_id=1, db=mock_db)
            
            assert len(result) == 1
            assert result[0]["name"] == "test.txt"

    @pytest.mark.asyncio
    async def test_read_file_server_not_found(self, mock_db):
        """Test read_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(ServerNotFoundException):
            await file_management_service.read_file(server_id=999, file_path="test.txt", db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    async def test_read_file_path_traversal(self, mock_exists, mock_server, mock_db):
        """Test read_file with path traversal attempt"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/etc/passwd"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            
            with pytest.raises(AccessDeniedException):
                await file_management_service.read_file(
                    server_id=1, file_path="../../../etc/passwd", db=mock_db
                )

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    async def test_read_file_not_found(self, mock_exists, mock_server, mock_db):
        """Test read_file when file doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = False
        
        with pytest.raises(FileOperationException):
            await file_management_service.read_file(server_id=1, file_path="nonexistent.txt", db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    async def test_read_file_is_directory(self, mock_is_dir, mock_exists, mock_server, mock_db):
        """Test read_file when target is a directory"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/directory"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            
            with pytest.raises(FileOperationException):
                await file_management_service.read_file(server_id=1, file_path="directory", db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('aiofiles.open')
    async def test_read_file_success(self, mock_aiofiles_open, mock_is_dir, mock_exists, mock_server, mock_db):
        """Test successful file read"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = True
        mock_is_dir.return_value = False
        
        mock_file = AsyncMock()
        mock_file.read.return_value = "file content"
        mock_aiofiles_open.return_value.__aenter__.return_value = mock_file
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            with patch('pathlib.Path.suffix', ".txt"):
                result = await file_management_service.read_file(server_id=1, file_path="test.txt", db=mock_db)
                
                assert result == "file content"

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('aiofiles.open')
    async def test_read_file_unicode_error(self, mock_aiofiles_open, mock_is_dir, mock_exists, mock_server, mock_db):
        """Test read_file with unicode decode error"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = True
        mock_is_dir.return_value = False
        
        mock_aiofiles_open.side_effect = UnicodeDecodeError('utf-8', b'', 0, 1, 'invalid')
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/binary.txt"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            with patch('pathlib.Path.suffix', ".txt"):
                with pytest.raises(InvalidRequestException):
                    await file_management_service.read_file(server_id=1, file_path="binary.txt", db=mock_db)

    @pytest.mark.asyncio
    async def test_write_file_server_not_found(self, mock_db):
        """Test write_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(ServerNotFoundException):
            await file_management_service.write_file(
                server_id=999, file_path="test.txt", content="content", db=mock_db
            )

    @pytest.mark.asyncio
    @patch('pathlib.Path.resolve')
    async def test_write_file_path_traversal(self, mock_resolve, mock_server, mock_user, mock_db):
        """Test write_file with path traversal attempt"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_resolve.side_effect = [
            Path("/etc/passwd"),  # target_path.resolve()
            Path("/servers/test_server")  # server_path.resolve()
        ]
        
        with pytest.raises(AccessDeniedException):
            await file_management_service.write_file(
                server_id=1, 
                file_path="../../../etc/passwd", 
                content="content", 
                user=mock_user, 
                db=mock_db
            )

    @pytest.mark.asyncio
    async def test_write_file_restricted_non_admin(self, mock_server, mock_user, mock_db):
        """Test write_file restricted file by non-admin user"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/ops.json"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            with patch('pathlib.Path.name', "ops.json"):
                with pytest.raises(AccessDeniedException):
                    await file_management_service.write_file(
                        server_id=1, 
                        file_path="ops.json", 
                        content="[]", 
                        user=mock_user, 
                        db=mock_db
                    )

    @pytest.mark.asyncio
    @patch('pathlib.Path.mkdir')
    @patch('pathlib.Path.exists')
    @patch('aiofiles.open')
    async def test_write_file_success(self, mock_aiofiles_open, mock_exists, mock_mkdir, mock_server, mock_user, mock_db):
        """Test successful file write"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = False
        
        mock_file = AsyncMock()
        mock_aiofiles_open.return_value.__aenter__.return_value = mock_file
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            with patch('pathlib.Path.suffix', ".txt"):
                with patch('pathlib.Path.name', "test.txt"):
                    with patch('pathlib.Path.stat') as mock_stat:
                        mock_stat.return_value.st_size = 7
                        mock_stat.return_value.st_mtime = 1640995200
                        with patch('pathlib.Path.is_dir', return_value=False):
                            with patch('pathlib.Path.is_file', return_value=True):
                                with patch('pathlib.Path.relative_to', return_value=Path("test.txt")):
                                    result = await file_management_service.write_file(
                                        server_id=1,
                                        file_path="test.txt",
                                        content="content",
                                        user=mock_user,
                                        db=mock_db
                                    )
                                    
                                    assert "updated successfully" in result["message"]
                                    assert result["file"]["name"] == "test.txt"
                                    mock_file.write.assert_called_once_with("content")

    @pytest.mark.asyncio
    async def test_delete_file_server_not_found(self, mock_db):
        """Test delete_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(ServerNotFoundException):
            await file_management_service.delete_file(server_id=999, file_path="test.txt", db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    async def test_delete_file_not_found(self, mock_exists, mock_server, mock_user, mock_db):
        """Test delete_file when file doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = False
        
        with pytest.raises(FileOperationException):
            await file_management_service.delete_file(server_id=1, file_path="nonexistent.txt", user=mock_user, db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_file')
    @patch('pathlib.Path.unlink')
    async def test_delete_file_success(self, mock_unlink, mock_is_file, mock_exists, mock_server, mock_admin_user, mock_db):
        """Test successful file deletion"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = True
        mock_is_file.return_value = True
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            with patch('pathlib.Path.suffix', ".txt"):
                with patch('pathlib.Path.name', "test.txt"):
                    with patch('pathlib.Path.is_dir', return_value=False):
                        result = await file_management_service.delete_file(
                            server_id=1, 
                            file_path="test.txt", 
                            user=mock_admin_user, 
                            db=mock_db
                        )
                        
                        assert "deleted successfully" in result["message"]
                        mock_unlink.assert_called_once()

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('shutil.rmtree')
    async def test_delete_directory_success(self, mock_rmtree, mock_is_dir, mock_exists, mock_server, mock_admin_user, mock_db):
        """Test successful directory deletion"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test_dir"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            with patch('pathlib.Path.is_file', return_value=False):
                with patch('pathlib.Path.name', "test_dir"):
                    result = await file_management_service.delete_file(
                        server_id=1, 
                        file_path="test_dir", 
                        user=mock_admin_user, 
                        db=mock_db
                    )
                    
                    assert "Directory" in result["message"]
                    assert "deleted successfully" in result["message"]
                    mock_rmtree.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_file_server_not_found(self, mock_db):
        """Test upload_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        mock_file = Mock(spec=UploadFile)
        mock_file.filename = "test.txt"
        
        with pytest.raises(ServerNotFoundException):
            await file_management_service.upload_file(server_id=999, file=mock_file, db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.mkdir')
    @patch('aiofiles.open')
    async def test_upload_file_success(self, mock_aiofiles_open, mock_mkdir, mock_server, mock_user, mock_db):
        """Test successful file upload"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        
        mock_file = Mock(spec=UploadFile)
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"file content")
        
        mock_aio_file = AsyncMock()
        mock_aiofiles_open.return_value.__aenter__.return_value = mock_aio_file
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server"),  # target_dir.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            
            result = await file_management_service.upload_file(
                server_id=1,
                file=mock_file,
                user=mock_user,
                db=mock_db
            )
            
            assert "uploaded successfully" in result["message"]
            assert result["filename"] == "test.txt"
            mock_aio_file.write.assert_called_once_with(b"file content")

    @pytest.mark.asyncio
    async def test_download_file_server_not_found(self, mock_db):
        """Test download_file when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(ServerNotFoundException):
            await file_management_service.download_file(server_id=999, file_path="test.txt", db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    async def test_download_file_success(self, mock_is_dir, mock_exists, mock_server, mock_db):
        """Test successful file download"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        mock_exists.return_value = True
        mock_is_dir.return_value = False
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/test.txt"),  # target_path.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            with patch('pathlib.Path.suffix', ".txt"):
                with patch('pathlib.Path.name', "test.txt"):
                    result = await file_management_service.download_file(server_id=1, file_path="test.txt", db=mock_db)
                    
                    file_path, filename = result
                    assert filename == "test.txt"

    @pytest.mark.asyncio
    async def test_create_directory_server_not_found(self, mock_db):
        """Test create_directory when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(ServerNotFoundException):
            await file_management_service.create_directory(server_id=999, directory_path="testdir", db=mock_db)

    @pytest.mark.asyncio
    @patch('pathlib.Path.mkdir')
    async def test_create_directory_success(self, mock_mkdir, mock_server, mock_db):
        """Test successful directory creation"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test_server/newdir"),  # target_dir.resolve()
                Path("/servers/test_server")  # server_path.resolve()
            ]
            
            result = await file_management_service.create_directory(
                server_id=1,
                directory_path="newdir",
                db=mock_db
            )
            
            assert "created successfully" in result["message"]
            mock_mkdir.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_files_server_not_found(self, mock_db):
        """Test search_files when server doesn't exist"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(ServerNotFoundException):
            await file_management_service.search_files(
                server_id=999, search_term="test", db=mock_db
            )

    @pytest.mark.asyncio
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.rglob')
    async def test_search_files_success(self, mock_rglob, mock_exists, mock_server, mock_db):
        """Test successful file search"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_server
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
            server_id=1,
            search_term="server",
            db=mock_db
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
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/servers/test/subdir/file.txt"),  # target.resolve()
                Path("/servers/test")  # base.resolve()
            ]
            
            result = service._is_safe_path(
                Path("/servers/test"), 
                Path("/servers/test/subdir/file.txt")
            )
            assert result

    def test_is_safe_path_invalid(self):
        """Test _is_safe_path with invalid path traversal"""
        service = file_management_service.validation_service
        
        with patch('pathlib.Path.resolve') as mock_resolve:
            # Mock the relative_to method to raise ValueError for path traversal
            mock_target_resolved = Mock()
            mock_base_resolved = Mock()
            mock_target_resolved.relative_to.side_effect = ValueError("Path traversal")
            
            mock_resolve.side_effect = [mock_target_resolved, mock_base_resolved]
            
            result = service._is_safe_path(
                Path("/servers/test"), 
                Path("/servers/test/../../../etc/passwd")
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
        
        with patch('pathlib.Path.is_dir', return_value=False):
            result = service._is_writable_file(Path("test.txt"))
            assert result

    def test_is_writable_file_not_allowed(self):
        """Test _is_writable_file with not allowed extension"""
        service = file_management_service.validation_service
        
        with patch('pathlib.Path.is_dir', return_value=False):
            result = service._is_writable_file(Path("test.jar"))
            assert not result

    def test_is_writable_file_directory(self):
        """Test _is_writable_file with directory"""
        service = file_management_service.validation_service
        
        with patch('pathlib.Path.is_dir', return_value=True):
            result = service._is_writable_file(Path("testdir"))
            assert not result

    def test_is_restricted_file(self):
        """Test _is_restricted_file"""
        service = file_management_service.validation_service
        
        result = service._is_restricted_file(Path("ops.json"))
        assert result
        
        result = service._is_restricted_file(Path("test.txt"))
        assert not result