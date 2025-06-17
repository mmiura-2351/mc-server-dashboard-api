import pytest
import json
import tempfile
from unittest.mock import Mock, patch, AsyncMock, mock_open
from pathlib import Path

from app.services.real_time_server_commands import RealTimeServerCommandService, real_time_server_commands
from app.servers.models import ServerStatus
from app.groups.models import GroupType
from app.core.security import SecurityError


class TestRealTimeServerCommandService:
    """Test class for RealTimeServerCommandService"""

    @pytest.fixture
    def service(self):
        return RealTimeServerCommandService()

    @pytest.fixture
    def mock_server_path(self):
        return Path("/test/servers/test_server")

    @pytest.fixture
    def mock_ops_data(self):
        return [
            {"uuid": "123-456", "name": "player1", "level": 4},
            {"uuid": "789-012", "name": "player2", "level": 4}
        ]

    def test_service_initialization(self, service):
        """Test RealTimeServerCommandService initialization"""
        assert isinstance(service, RealTimeServerCommandService)
        assert service.base_directory == Path("servers")

    def test_global_service_instance(self):
        """Test global real_time_server_commands instance"""
        assert real_time_server_commands is not None
        assert isinstance(real_time_server_commands, RealTimeServerCommandService)

    # Test _validate_server_path
    @patch('app.services.real_time_server_commands.FileOperationValidator')
    def test_validate_server_path_success(self, mock_validator, service):
        """Test successful server path validation"""
        mock_path = Mock()
        mock_path.parent = Path("/test/servers/test_server")
        mock_validator.validate_server_file_path.return_value = mock_path

        result = service._validate_server_path("test_server")

        assert result == Path("/test/servers/test_server")
        mock_validator.validate_server_file_path.assert_called_once_with(
            "test_server", ".", service.base_directory
        )

    @patch('app.services.real_time_server_commands.FileOperationValidator')
    def test_validate_server_path_security_error(self, mock_validator, service):
        """Test server path validation with security error"""
        mock_validator.validate_server_file_path.side_effect = SecurityError("Invalid path")

        with pytest.raises(SecurityError):
            service._validate_server_path("../malicious_path")

    # Test reload_whitelist_if_running
    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_reload_whitelist_if_running_success(self, mock_manager, service):
        """Test successful whitelist reload for running server"""
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.send_command = AsyncMock(return_value=True)

        result = await service.reload_whitelist_if_running(1)

        assert result is True
        mock_manager.get_server_status.assert_called_once_with(1)
        mock_manager.send_command.assert_called_once_with(1, "whitelist reload")

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_reload_whitelist_if_running_server_not_running(self, mock_manager, service):
        """Test whitelist reload when server is not running"""
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        result = await service.reload_whitelist_if_running(1)

        assert result is False
        mock_manager.get_server_status.assert_called_once_with(1)
        mock_manager.send_command.assert_not_called()

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_reload_whitelist_if_running_command_failed(self, mock_manager, service):
        """Test whitelist reload when command fails"""
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.send_command = AsyncMock(return_value=False)

        result = await service.reload_whitelist_if_running(1)

        assert result is False
        mock_manager.send_command.assert_called_once_with(1, "whitelist reload")

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_reload_whitelist_if_running_exception(self, mock_manager, service):
        """Test whitelist reload with exception"""
        mock_manager.get_server_status.side_effect = Exception("Server manager error")

        result = await service.reload_whitelist_if_running(1)

        assert result is False

    # Test sync_op_changes_if_running
    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_sync_op_changes_if_running_success(self, mock_manager, service, mock_server_path, mock_ops_data):
        """Test successful OP sync for running server"""
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.send_command = AsyncMock(return_value=True)

        # Mock file operations
        with patch('builtins.open', mock_open(read_data=json.dumps(mock_ops_data))):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'resolve') as mock_resolve:
                    mock_resolve.return_value.relative_to.return_value = Path("ops.json")
                    
                    result = await service.sync_op_changes_if_running(1, mock_server_path)

        assert result is True
        mock_manager.get_server_status.assert_called_once_with(1)
        # Should send OP commands for both players
        assert mock_manager.send_command.call_count == 2

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_sync_op_changes_if_running_server_not_running(self, mock_manager, service, mock_server_path):
        """Test OP sync when server is not running"""
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        result = await service.sync_op_changes_if_running(1, mock_server_path)

        assert result is False
        mock_manager.send_command.assert_not_called()

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_sync_op_changes_if_running_no_ops_file(self, mock_manager, service, mock_server_path):
        """Test OP sync when ops.json doesn't exist"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        with patch.object(Path, 'exists', return_value=False):
            with patch.object(Path, 'resolve') as mock_resolve:
                mock_resolve.return_value.relative_to.return_value = Path("ops.json")
                
                result = await service.sync_op_changes_if_running(1, mock_server_path)

        assert result is True  # Should succeed with empty ops list
        mock_manager.send_command.assert_not_called()

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_sync_op_changes_if_running_invalid_json(self, mock_manager, service, mock_server_path):
        """Test OP sync with invalid JSON file"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        with patch('builtins.open', mock_open(read_data="invalid json")):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'resolve') as mock_resolve:
                    mock_resolve.return_value.relative_to.return_value = Path("ops.json")
                    
                    result = await service.sync_op_changes_if_running(1, mock_server_path)

        assert result is False

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_sync_op_changes_if_running_path_traversal(self, mock_manager, service, mock_server_path):
        """Test OP sync with path traversal attempt"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        with patch.object(Path, 'resolve') as mock_resolve:
            mock_resolve.return_value.relative_to.side_effect = ValueError("Path outside directory")
            
            result = await service.sync_op_changes_if_running(1, mock_server_path)

        assert result is False

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_sync_op_changes_if_running_partial_success(self, mock_manager, service, mock_server_path, mock_ops_data):
        """Test OP sync with partial command success"""
        mock_manager.get_server_status.return_value = ServerStatus.running
        # First command succeeds, second fails
        mock_manager.send_command.side_effect = [True, False]

        with patch('builtins.open', mock_open(read_data=json.dumps(mock_ops_data))):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'resolve') as mock_resolve:
                    mock_resolve.return_value.relative_to.return_value = Path("ops.json")
                    
                    result = await service.sync_op_changes_if_running(1, mock_server_path)

        assert result is False  # Should be False if not all commands succeeded

    # Test apply_op_diff_if_running
    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_apply_op_diff_if_running_success(self, mock_manager, service):
        """Test successful OP diff application"""
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.send_command = AsyncMock(return_value=True)

        added_players = {"player1", "player2"}
        removed_players = {"player3"}

        result = await service.apply_op_diff_if_running(1, added_players, removed_players)

        assert result is True
        assert mock_manager.send_command.call_count == 3  # 2 op + 1 deop commands

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_apply_op_diff_if_running_server_not_running(self, mock_manager, service):
        """Test OP diff when server is not running"""
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        result = await service.apply_op_diff_if_running(1, {"player1"}, {"player2"})

        assert result is False
        mock_manager.send_command.assert_not_called()

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_apply_op_diff_if_running_empty_sets(self, mock_manager, service):
        """Test OP diff with empty player sets"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        result = await service.apply_op_diff_if_running(1, set(), set())

        assert result is True  # Should succeed with no operations
        mock_manager.send_command.assert_not_called()

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_apply_op_diff_if_running_command_exception(self, mock_manager, service):
        """Test OP diff with command exception"""
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.send_command.side_effect = Exception("Command failed")

        result = await service.apply_op_diff_if_running(1, {"player1"}, set())

        assert result is False

    # Test handle_group_change_commands
    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_handle_group_change_commands_whitelist_update(self, mock_manager, service, mock_server_path):
        """Test group change handling for whitelist update"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        with patch.object(service, 'reload_whitelist_if_running', return_value=True) as mock_reload:
            result = await service.handle_group_change_commands(
                1, mock_server_path, GroupType.whitelist, "update"
            )

        assert result is True
        mock_reload.assert_called_once_with(1)

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_handle_group_change_commands_op_update(self, mock_manager, service, mock_server_path):
        """Test group change handling for OP update"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        with patch.object(service, 'sync_op_changes_if_running', return_value=True) as mock_sync:
            result = await service.handle_group_change_commands(
                1, mock_server_path, GroupType.op, "update"
            )

        assert result is True
        mock_sync.assert_called_once_with(1, mock_server_path)

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_handle_group_change_commands_op_player_remove(self, mock_manager, service, mock_server_path):
        """Test group change handling for OP player removal"""
        mock_manager.get_server_status.return_value = ServerStatus.running
        removed_player = {"username": "player1", "uuid": "123-456"}

        with patch.object(service, 'apply_op_diff_if_running', return_value=True) as mock_diff:
            result = await service.handle_group_change_commands(
                1, mock_server_path, GroupType.op, "player_remove", removed_player
            )

        assert result is True
        mock_diff.assert_called_once_with(1, set(), {"player1"})

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_handle_group_change_commands_server_not_running(self, mock_manager, service, mock_server_path):
        """Test group change handling when server is not running"""
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        result = await service.handle_group_change_commands(
            1, mock_server_path, GroupType.whitelist, "update"
        )

        assert result is True  # Should return True since file update already happened

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_handle_group_change_commands_whitelist_failed(self, mock_manager, service, mock_server_path):
        """Test group change handling when whitelist reload fails"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        with patch.object(service, 'reload_whitelist_if_running', return_value=False):
            result = await service.handle_group_change_commands(
                1, mock_server_path, GroupType.whitelist, "update"
            )

        assert result is False

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_handle_group_change_commands_op_player_remove_no_username(self, mock_manager, service, mock_server_path):
        """Test group change handling for OP player removal without username"""
        mock_manager.get_server_status.return_value = ServerStatus.running
        removed_player = {"uuid": "123-456"}  # Missing username

        result = await service.handle_group_change_commands(
            1, mock_server_path, GroupType.op, "player_remove", removed_player
        )

        assert result is False

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_handle_group_change_commands_op_sync_failed(self, mock_manager, service, mock_server_path):
        """Test group change handling when OP sync fails"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        with patch.object(service, 'sync_op_changes_if_running', return_value=False):
            result = await service.handle_group_change_commands(
                1, mock_server_path, GroupType.op, "update"
            )

        assert result is False

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_handle_group_change_commands_exception(self, mock_manager, service, mock_server_path):
        """Test group change handling with exception"""
        mock_manager.get_server_status.side_effect = Exception("Server manager error")

        result = await service.handle_group_change_commands(
            1, mock_server_path, GroupType.whitelist, "update"
        )

        assert result is False

    # Test edge cases and error handling
    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_sync_op_changes_ops_file_permission_error(self, mock_manager, service, mock_server_path):
        """Test OP sync with file permission error"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'resolve') as mock_resolve:
                    mock_resolve.return_value.relative_to.return_value = Path("ops.json")
                    
                    result = await service.sync_op_changes_if_running(1, mock_server_path)

        assert result is False

    @pytest.mark.asyncio
    @patch('app.services.real_time_server_commands.minecraft_server_manager')
    async def test_sync_op_changes_malformed_ops_data(self, mock_manager, service, mock_server_path):
        """Test OP sync with malformed ops data"""
        mock_manager.get_server_status.return_value = ServerStatus.running
        
        # Ops data missing name field
        malformed_data = [{"uuid": "123-456", "level": 4}]

        with patch('builtins.open', mock_open(read_data=json.dumps(malformed_data))):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'resolve') as mock_resolve:
                    mock_resolve.return_value.relative_to.return_value = Path("ops.json")
                    
                    result = await service.sync_op_changes_if_running(1, mock_server_path)

        assert result is True  # Should succeed with no valid names to process
        mock_manager.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_various_server_statuses_handling(self, service):
        """Test handling of various server statuses"""
        test_statuses = [
            ServerStatus.stopped,
            ServerStatus.starting,
            ServerStatus.stopping,
            ServerStatus.error
        ]

        with patch('app.services.real_time_server_commands.minecraft_server_manager') as mock_manager:
            for status in test_statuses:
                mock_manager.get_server_status.return_value = status
                
                # All these should return False for non-running status
                if status != ServerStatus.running:
                    result = await service.reload_whitelist_if_running(1)
                    assert result is False
                    
                    result = await service.apply_op_diff_if_running(1, {"player1"}, set())
                    assert result is False

    def test_service_directory_initialization_with_custom_path(self):
        """Test service initialization with custom base directory"""
        custom_service = RealTimeServerCommandService()
        custom_service.base_directory = Path("/custom/servers")
        
        assert custom_service.base_directory == Path("/custom/servers")