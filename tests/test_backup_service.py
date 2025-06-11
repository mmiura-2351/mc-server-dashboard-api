import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from datetime import datetime

from app.services.backup_service import BackupService, backup_service
from app.core.exceptions import (
    BackupNotFoundException,
    ServerNotFoundException,
    FileOperationException,
    DatabaseOperationException
)
from app.servers.models import Backup, BackupStatus, BackupType, Server


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
    """Test BackupService class"""
    
    @pytest.fixture
    def service(self):
        with patch('pathlib.Path.mkdir'):
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
                backup_type=BackupType.manual,
                db=mock_db
            )
    
    @pytest.mark.asyncio
    @patch('app.services.minecraft_server.minecraft_server_manager.get_server_status')
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
        with patch.object(service.file_service, 'create_backup_file', return_value="backup_1_1_20240101_120000.tar.gz"):
            with patch('pathlib.Path.stat') as mock_stat:
                mock_stat.return_value.st_size = 1024000
                
                result = await service.create_backup(
                    server_id=1,
                    name="test_backup",
                    backup_type=BackupType.manual,
                    db=mock_db
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
        
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.unlink'):
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
        
        result = service.list_backups(server_id=1, db=mock_db)
        
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
        
        result = service.get_backup_statistics(server_id=1, db=mock_db)
        
        assert result["total_backups"] == 10
        assert result["completed_backups"] == 8
        assert result["failed_backups"] == 2
        assert result["total_size_bytes"] == 3000000


def test_global_backup_service_instance():
    """Test that global backup_service instance exists"""
    assert backup_service is not None
    assert isinstance(backup_service, BackupService)