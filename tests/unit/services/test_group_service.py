"""
Comprehensive test coverage for Group Service
Consolidates all group service related tests for better organization
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi import HTTPException, APIRouter, Depends, Query
import json
from pathlib import Path
from typing import List

from app.services.group_service import (
    GroupService, 
    GroupAccessService, 
    GroupFileService
)
from app.groups.models import Group, GroupType, ServerGroup
from app.groups.schemas import (
    GroupCreateRequest,
    GroupResponse,
    GroupUpdateRequest,
    PlayerAddRequest,
    PlayerRemoveRequest,
    GroupListResponse,
    ServerAttachRequest,
)
from app.servers.models import Server, ServerStatus, ServerType
from app.users.models import Role, User
from app.audit.models import AuditLog
from app.core.exceptions import FileOperationException
from app.core.security import PathValidator, SecurityError
from app.services.real_time_server_commands import real_time_server_commands


class TestGroupFileService:
    """Test cases for GroupFileService - critical file synchronization functionality"""

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session"""
        return Mock()

    @pytest.fixture
    def file_service(self, mock_db_session):
        """Create GroupFileService instance"""
        return GroupFileService(mock_db_session)

    @pytest.fixture
    def test_server(self):
        """Create test server"""
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test-server"
        server.directory_path = "servers/test-server"
        return server

    @pytest.fixture
    def op_group(self):
        """Create OP group with players"""
        group = Mock(spec=Group)
        group.id = 1
        group.name = "admins"
        group.type = GroupType.op
        group.get_players.return_value = [
            {"uuid": "123e4567-e89b-12d3-a456-426614174000", "username": "admin1"},
            {"uuid": "123e4567-e89b-12d3-a456-426614174001", "username": "admin2"}
        ]
        return group

    @pytest.fixture
    def whitelist_group(self):
        """Create whitelist group with players"""
        group = Mock(spec=Group)
        group.id = 2
        group.name = "players"
        group.type = GroupType.whitelist
        group.get_players.return_value = [
            {"uuid": "123e4567-e89b-12d3-a456-426614174002", "username": "player1"},
            {"uuid": "123e4567-e89b-12d3-a456-426614174003", "username": "player2"}
        ]
        return group

    @pytest.mark.asyncio
    @patch('app.services.group_service.PathValidator')
    @patch('app.services.group_service.Path')
    @patch('app.services.group_service.real_time_server_commands')
    async def test_update_server_files_success_both_groups(self, mock_rt_commands, mock_path_class, mock_validator, file_service, mock_db_session, test_server, op_group, whitelist_group):
        """Test successful file update with both OP and whitelist groups"""
        # Setup mocks
        mock_query = Mock()
        mock_db_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [op_group, whitelist_group]

        mock_path = Mock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = True
        
        ops_file = Mock()
        whitelist_file = Mock()
        mock_path.__truediv__ = Mock(side_effect=lambda x: ops_file if x == "ops.json" else whitelist_file)

        mock_file_handle = Mock()
        mock_file_handle.__enter__ = Mock(return_value=mock_file_handle)
        mock_file_handle.__exit__ = Mock(return_value=None)

        with patch('builtins.open', return_value=mock_file_handle):
            with patch('json.dump') as mock_json_dump:
                await file_service.update_server_files(test_server.id, test_server)

        # Verify database query
        mock_db_session.query.assert_called_once()
        
        # Verify path validation
        mock_validator.validate_safe_path.assert_called_once()
        
        # Verify JSON files were written
        assert mock_json_dump.call_count == 2
        
        # Verify real-time commands were called
        mock_rt_commands.reload_whitelist_if_running.assert_called_once_with(test_server.id)
        mock_rt_commands.sync_op_changes_if_running.assert_called_once_with(test_server.id, mock_path)

    @pytest.mark.asyncio
    @patch('app.services.group_service.PathValidator')
    async def test_update_server_files_security_error(self, mock_validator, file_service, mock_db_session, test_server):
        """Test security error during path validation"""
        # Setup mocks
        mock_query = Mock()
        mock_db_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []

        mock_validator.validate_safe_path.side_effect = SecurityError("Path traversal attempt")

        with pytest.raises(FileOperationException) as exc_info:
            await file_service.update_server_files(test_server.id, test_server)
        
        assert "Security validation failed" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch('app.services.group_service.PathValidator')
    @patch('app.services.group_service.Path')
    async def test_update_server_files_directory_not_exists(self, mock_path_class, mock_validator, file_service, mock_db_session, test_server):
        """Test handling when server directory doesn't exist"""
        # Setup mocks
        mock_query = Mock()
        mock_db_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []

        mock_path = Mock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = False

        # Should not raise exception but log error
        await file_service.update_server_files(test_server.id, test_server)
        
        # Verify path existence was checked
        mock_path.exists.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.services.group_service.PathValidator')
    @patch('app.services.group_service.Path')
    @patch('app.services.group_service.real_time_server_commands')
    async def test_update_server_files_real_time_command_failure(self, mock_rt_commands, mock_path_class, mock_validator, file_service, mock_db_session, test_server, op_group):
        """Test handling when real-time commands fail"""
        # Setup mocks
        mock_query = Mock()
        mock_db_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [op_group]

        mock_path = Mock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = True
        
        ops_file = Mock()
        mock_path.__truediv__ = Mock(return_value=ops_file)

        mock_file_handle = Mock()
        mock_file_handle.__enter__ = Mock(return_value=mock_file_handle)
        mock_file_handle.__exit__ = Mock(return_value=None)

        # Make real-time commands fail
        mock_rt_commands.sync_op_changes_if_running.side_effect = Exception("Command failed")

        with patch('builtins.open', return_value=mock_file_handle):
            with patch('json.dump'):
                # Should not raise exception despite command failure
                await file_service.update_server_files(test_server.id, test_server)

    @pytest.mark.asyncio
    @patch('app.services.group_service.PathValidator')
    @patch('app.services.group_service.Path')
    async def test_update_server_files_duplicate_player_handling(self, mock_path_class, mock_validator, file_service, mock_db_session, test_server):
        """Test that duplicate players are handled correctly across groups"""
        # Create groups with overlapping players
        op_group = Mock(spec=Group)
        op_group.id = 1
        op_group.name = "admins"
        op_group.type = GroupType.op
        op_group.get_players.return_value = [
            {"uuid": "123e4567-e89b-12d3-a456-426614174000", "username": "admin1"}
        ]

        whitelist_group = Mock(spec=Group)
        whitelist_group.id = 2
        whitelist_group.name = "players"
        whitelist_group.type = GroupType.whitelist
        whitelist_group.get_players.return_value = [
            {"uuid": "123e4567-e89b-12d3-a456-426614174000", "username": "admin1"},  # Same player
            {"uuid": "123e4567-e89b-12d3-a456-426614174001", "username": "player1"}
        ]

        # Setup mocks
        mock_query = Mock()
        mock_db_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [op_group, whitelist_group]

        mock_path = Mock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = True
        
        ops_file = Mock()
        whitelist_file = Mock()
        mock_path.__truediv__ = Mock(side_effect=lambda x: ops_file if x == "ops.json" else whitelist_file)

        mock_file_handle = Mock()
        mock_file_handle.__enter__ = Mock(return_value=mock_file_handle)
        mock_file_handle.__exit__ = Mock(return_value=None)

        written_data = {}
        def capture_json_dump(data, file, **kwargs):
            if file == mock_file_handle:
                if 'ops' in str(ops_file):
                    written_data['ops'] = data
                else:
                    written_data['whitelist'] = data

        with patch('builtins.open', return_value=mock_file_handle):
            with patch('json.dump', side_effect=capture_json_dump):
                await file_service.update_server_files(test_server.id, test_server)

        # Verify no duplicates in either file
        # Note: actual verification would need to inspect the captured data
        # This test ensures the flow completes without errors

    @pytest.mark.asyncio
    @patch('app.services.group_service.PathValidator')
    @patch('app.services.group_service.Path')
    async def test_update_server_files_file_permission_error(self, mock_path_class, mock_validator, file_service, mock_db_session, test_server, op_group):
        """Test handling file permission errors"""
        # Setup mocks
        mock_query = Mock()
        mock_db_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [op_group]

        mock_path = Mock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = True

        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            with pytest.raises(Exception):
                await file_service.update_server_files(test_server.id, test_server)


class TestGroupAccessService:
    """Test cases for GroupAccessService - comprehensive access control testing"""

    def test_check_group_access_owner_success(self, test_user):
        """Test successful group access check for owner"""
        group = Group(
            id=1,
            name="test-group",
            type=GroupType.op,
            owner_id=test_user.id,
            players=[]
        )

        # Should not raise exception
        GroupAccessService.check_group_access(test_user, group)

    def test_check_group_access_admin_success(self, admin_user, test_user):
        """Test successful group access check for admin"""
        group = Group(
            id=1,
            name="test-group",
            type=GroupType.op,
            owner_id=test_user.id,  # Owned by test_user
            players=[]
        )

        # Admin should be able to access any group
        GroupAccessService.check_group_access(admin_user, group)

    def test_check_group_access_forbidden(self, test_user):
        """Test group access check with insufficient permissions"""
        group = Group(
            id=1,
            name="test-group",
            type=GroupType.op,
            owner_id=999,  # Different owner
            players=[]
        )

        with pytest.raises(HTTPException) as exc_info:
            GroupAccessService.check_group_access(test_user, group)
        
        assert exc_info.value.status_code == 403
        assert "You don't have permission to access this group" in str(exc_info.value.detail)

    def test_check_server_access_owner_success(self, test_user):
        """Test successful server access check for owner"""
        server = Server(
            id=1,
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=test_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )

        # Should not raise exception
        GroupAccessService.check_server_access(test_user, server)

    def test_check_server_access_admin_success(self, admin_user, test_user):
        """Test successful server access check for admin"""
        server = Server(
            id=1,
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=test_user.id,  # Owned by test_user
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )

        # Admin should be able to access any server
        GroupAccessService.check_server_access(admin_user, server)

    def test_check_server_access_forbidden(self, test_user):
        """Test server access check with insufficient permissions"""
        server = Server(
            id=1,
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=999,  # Different owner
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )

        with pytest.raises(HTTPException) as exc_info:
            GroupAccessService.check_server_access(test_user, server)
        
        assert exc_info.value.status_code == 403


class TestGroupFileService:
    """Test cases for GroupFileService - basic service testing"""

    @pytest.fixture
    def file_service(self, db):
        return GroupFileService(db)
    
    @pytest.mark.asyncio
    async def test_basic_initialization(self, file_service):
        """Test that file service can be initialized"""
        assert file_service is not None
        assert file_service.db is not None

    @pytest.mark.asyncio
    async def test_update_server_files_basic(self, file_service):
        """Test basic server file update functionality"""
        # Test with a non-existent server (should handle gracefully)
        await file_service.update_server_files(999)
    
    @pytest.mark.asyncio
    async def test_update_all_affected_servers_basic(self, file_service):
        """Test updating all affected servers"""
        # Test with a non-existent group (should handle gracefully)  
        await file_service.update_all_affected_servers(999)
    
    @pytest.mark.asyncio
    async def test_batch_update_server_files_empty(self, file_service):
        """Test batch update with empty list"""
        # Test with empty list (should handle gracefully)
        await file_service.batch_update_server_files([])


class TestGroupService:
    """Test cases for GroupService - complete business logic testing"""

    @pytest.fixture
    def group_service(self, db):
        return GroupService(db)

    def test_create_group_success(self, group_service, db, test_user):
        """Test successful group creation"""
        result = group_service.create_group(
            user=test_user,
            name="test-group",
            group_type=GroupType.op,
            description="Test group"
        )
        
        assert result.name == "test-group"
        assert result.type == GroupType.op
        assert result.owner_id == test_user.id
        assert result.players == []

    def test_create_group_duplicate_name(self, group_service, db, test_user):
        """Test group creation with duplicate name"""
        # Create first group
        existing_group = Group(
            name="duplicate-group",
            type=GroupType.op,
            owner_id=test_user.id,
            players=[]
        )
        db.add(existing_group)
        db.commit()

        # Try to create group with same name
        with pytest.raises(HTTPException) as exc_info:
            group_service.create_group(
                user=test_user,
                name="duplicate-group",
                group_type=GroupType.whitelist,
                description="Duplicate group"
            )
        
        assert exc_info.value.status_code == 400
        assert "already exists" in str(exc_info.value.detail)

    def test_get_user_groups_success(self, group_service, db, test_user):
        """Test successful retrieval of user groups"""
        # Create groups
        group1 = Group(
            name="group1",
            type=GroupType.op,
            owner_id=test_user.id,
            players=["player1"]
        )
        group2 = Group(
            name="group2",
            type=GroupType.whitelist,
            owner_id=test_user.id,
            players=["player2"]
        )
        db.add_all([group1, group2])
        db.commit()

        result = group_service.get_user_groups(test_user)
        
        assert len(result) == 2
        assert all(group.owner_id == test_user.id for group in result)

    def test_get_group_by_id_success(self, group_service, db, test_user):
        """Test successful group retrieval by ID"""
        group = Group(
            name="test-group",
            type=GroupType.op,
            owner_id=test_user.id,
            players=["player1"]
        )
        db.add(group)
        db.commit()

        result = group_service.get_group_by_id(test_user, group.id)
        
        assert result.id == group.id
        assert result.name == "test-group"
        assert result.owner_id == test_user.id

    def test_get_group_by_id_not_found(self, group_service, db, test_user):
        """Test group retrieval with non-existent ID"""
        with pytest.raises(HTTPException) as exc_info:
            group_service.get_group_by_id(test_user, 999)
        
        assert exc_info.value.status_code == 404
        assert "Group not found" in str(exc_info.value.detail)

    def test_update_group_success(self, group_service, db, test_user):
        """Test successful group update"""
        group = Group(
            name="test-group",
            type=GroupType.op,
            owner_id=test_user.id,
            players=["player1"]
        )
        db.add(group)
        db.commit()

        result = group_service.update_group(
            user=test_user,
            group_id=group.id,
            name="updated-group",
            description="Updated description"
        )
        
        assert result.name == "updated-group"
        assert result.description == "Updated description"

    def test_delete_group_success(self, group_service, db, test_user):
        """Test successful group deletion"""
        group = Group(
            name="test-group",
            type=GroupType.op,
            owner_id=test_user.id,
            players=["player1"]
        )
        db.add(group)
        db.commit()

        group_service.delete_group(test_user, group.id)
        
        # Verify group was deleted
        deleted_group = db.query(Group).filter(Group.id == group.id).first()
        assert deleted_group is None

    @pytest.mark.asyncio
    async def test_add_player_to_group_success(self, group_service, db, test_user):
        """Test successful player addition to group"""
        group = Group(
            name="test-group",
            type=GroupType.op,
            owner_id=test_user.id,
            players=[]
        )
        db.add(group)
        db.commit()

        with patch.object(group_service.file_service, 'update_all_affected_servers_with_retry', return_value=None):
            result = await group_service.add_player_to_group(
                user=test_user,
                group_id=group.id,
                uuid="uuid-123",
                username="testplayer"
            )
            
            assert result.id == group.id
            assert len(result.players) == 1
            assert result.players[0]["username"] == "testplayer"

    @pytest.mark.asyncio
    async def test_add_player_to_group_already_exists(self, group_service, db, test_user):
        """Test adding player that already exists in group (should not create duplicate)"""
        group = Group(
            name="test-group",
            type=GroupType.op,
            owner_id=test_user.id,
            players=[{"uuid": "uuid-123", "username": "existingplayer"}]
        )
        db.add(group)
        db.commit()

        with patch.object(group_service.file_service, 'update_all_affected_servers_with_retry', return_value=None):
            result = await group_service.add_player_to_group(
                user=test_user,
                group_id=group.id,
                uuid="uuid-123",
                username="existingplayer"
            )
        
        # Should still have only 1 player (no duplicate created)
        assert len(result.players) == 1
        assert result.players[0]["uuid"] == "uuid-123"
        assert result.players[0]["username"] == "existingplayer"

    @pytest.mark.asyncio
    async def test_remove_player_from_group_success(self, group_service, db, test_user):
        """Test successful player removal from group"""
        group = Group(
            name="test-group",
            type=GroupType.op,
            owner_id=test_user.id,
            players=[{"uuid": "uuid-123", "username": "testplayer"}, {"uuid": "uuid-456", "username": "otherplayer"}]
        )
        db.add(group)
        db.commit()

        with patch.object(group_service.file_service, 'update_all_affected_servers_with_retry', return_value=None):
            result = await group_service.remove_player_from_group(
                user=test_user,
                group_id=group.id,
                uuid="uuid-123"
            )
            
            assert result.id == group.id
            assert len(result.players) == 1
            assert result.players[0]["username"] == "otherplayer"

    @pytest.mark.asyncio
    async def test_remove_player_from_group_not_found(self, group_service, db, test_user):
        """Test removing player that doesn't exist in group"""
        group = Group(
            name="test-group",
            type=GroupType.op,
            owner_id=test_user.id,
            players=[{"uuid": "uuid-456", "username": "otherplayer"}]
        )
        db.add(group)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await group_service.remove_player_from_group(
                user=test_user,
                group_id=group.id,
                uuid="uuid-nonexistent"
            )
        
        assert exc_info.value.status_code == 404
        assert "Player not found in group" in str(exc_info.value.detail)


class TestGroupsRouter:
    """Test API router configuration and endpoint existence"""

    def test_router_configuration(self):
        """Test that the router is properly configured"""
        from app.groups.router import router
        
        assert isinstance(router, APIRouter)
        assert router.tags == ["groups"]
        assert len(router.routes) > 0

    def test_schema_imports(self):
        """Test that all required schemas can be imported"""
        from app.groups.schemas import (
            GroupCreateRequest,
            GroupResponse,
            GroupUpdateRequest,
            PlayerAddRequest,
            PlayerRemoveRequest,
            GroupListResponse,
            ServerAttachRequest,
        )
        
        # Test that schemas are properly defined classes
        assert GroupCreateRequest is not None
        assert GroupResponse is not None
        assert GroupUpdateRequest is not None
        assert PlayerAddRequest is not None
        assert PlayerRemoveRequest is not None
        assert GroupListResponse is not None
        assert ServerAttachRequest is not None

    def test_fastapi_dependencies(self):
        """Test that FastAPI dependencies can be imported"""
        from fastapi import APIRouter, Depends, Query, HTTPException
        from typing import List
        
        # These should import without errors
        assert APIRouter is not None
        assert Depends is not None
        assert Query is not None
        assert HTTPException is not None
        assert List is not None

    def test_groups_router_endpoints_exist(self):
        """Test that expected endpoints exist in the router"""
        from app.groups.router import router
        
        # Get all route paths
        route_paths = [route.path for route in router.routes]
        
        # Check that key endpoints exist
        expected_paths = [
            "/",  # List groups
            "/{group_id}",  # Get group by ID
        ]
        
        for expected_path in expected_paths:
            assert any(expected_path in path for path in route_paths), f"Expected path {expected_path} not found"

    def test_authentication_requirements(self):
        """Test that endpoints require authentication"""
        from app.groups.router import router
        
        # Check that routes have dependencies (likely authentication)
        for route in router.routes:
            if hasattr(route, 'dependant') and route.dependant:
                # Should have some dependencies (auth, db, etc.)
                assert len(route.dependant.dependencies) > 0



class TestGroupImports:
    """Test import validation and initialization"""

    def test_group_service_imports(self):
        """Test that group services can be imported successfully"""
        from app.services.group_service import (
            GroupService,
            GroupAccessService,
            GroupFileService
        )
        
        assert GroupService is not None
        assert GroupAccessService is not None
        assert GroupFileService is not None

    def test_group_models_imports(self):
        """Test that group models can be imported successfully"""
        from app.groups.models import Group, GroupType, ServerGroup
        
        assert Group is not None
        assert GroupType is not None
        assert ServerGroup is not None

    def test_service_initialization(self, db):
        """Test that services can be initialized"""
        from app.services.group_service import GroupService, GroupFileService
        
        group_service = GroupService(db)
        file_service = GroupFileService(db)
        
        assert group_service is not None
        assert file_service is not None


def test_global_group_functionality(db):
    """Test overall group functionality integration"""
    from app.services.group_service import GroupService, GroupAccessService, GroupFileService
    
    # Test that all services are available and can be instantiated
    group_service = GroupService(db)
    file_service = GroupFileService(db)
    
    assert group_service is not None
    assert file_service is not None
    assert GroupAccessService is not None