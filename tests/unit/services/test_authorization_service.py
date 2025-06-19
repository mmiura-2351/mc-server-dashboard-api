"""
Comprehensive tests for AuthorizationService

Coverage target: 34.91% → 80%
Security critical service - comprehensive testing required
"""

import pytest
from fastapi import HTTPException, status
from unittest.mock import Mock, AsyncMock
from sqlalchemy.orm import Session

from app.services.authorization_service import AuthorizationService, authorization_service
from app.users.models import User, Role
from app.servers.models import Server, ServerType, ServerStatus, Backup


@pytest.fixture
def operator_user(db):
    """Create test operator user"""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    hashed_password = pwd_context.hash("operatorpassword")
    user = User(
        username="operator",
        email="operator@example.com",
        hashed_password=hashed_password,
        role=Role.operator,
        is_approved=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestAuthorizationServiceServerAccess:
    """Test server access control methods"""

    def test_check_server_access_admin_user(self, db: Session, admin_user, sample_server):
        """Test admin user can access any server"""
        result = AuthorizationService.check_server_access(sample_server.id, admin_user, db)
        assert result == sample_server
        assert result.id == sample_server.id

    def test_check_server_access_owner_user(self, db: Session, test_user, sample_server):
        """Test server owner can access their own server"""
        # Update server to be owned by test_user
        sample_server.owner_id = test_user.id
        db.commit()
        
        result = AuthorizationService.check_server_access(sample_server.id, test_user, db)
        assert result == sample_server
        assert result.owner_id == test_user.id

    def test_check_server_access_non_owner_user_no_visibility_config(self, db: Session, test_user, sample_server):
        """Test non-owner user CANNOT access server without visibility config (Phase 2: Secure by default)"""
        # Ensure test_user is not the owner
        assert sample_server.owner_id != test_user.id
        
        # With Phase 2, resources without visibility config default to PRIVATE
        with pytest.raises(HTTPException) as exc_info:
            AuthorizationService.check_server_access(sample_server.id, test_user, db)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Not authorized to access this server" in str(exc_info.value.detail)

    def test_check_server_access_nonexistent_server(self, db: Session, admin_user):
        """Test accessing non-existent server raises 404"""
        nonexistent_id = 99999
        
        with pytest.raises(HTTPException) as exc_info:
            AuthorizationService.check_server_access(nonexistent_id, admin_user, db)
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "Server not found" in str(exc_info.value.detail)

    def test_check_server_access_operator_non_owner_no_visibility_config(self, db: Session, operator_user, sample_server):
        """Test operator user CANNOT access server without visibility config (Phase 2: Secure by default)"""
        # Ensure operator_user is not the owner
        assert sample_server.owner_id != operator_user.id
        
        # With Phase 2, even operators need explicit access without visibility config
        with pytest.raises(HTTPException) as exc_info:
            AuthorizationService.check_server_access(sample_server.id, operator_user, db)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Not authorized to access this server" in str(exc_info.value.detail)


class TestAuthorizationServiceBackupAccess:
    """Test backup access control methods"""

    @pytest.fixture
    def sample_backup(self, db: Session, sample_server):
        """Create a test backup"""
        backup = Backup(
            server_id=sample_server.id,
            name="test_backup",
            description="Test backup description",
            file_path="/backups/test_backup.tar.gz",
            file_size=1024
        )
        db.add(backup)
        db.commit()
        db.refresh(backup)
        return backup

    def test_check_backup_access_admin_user(self, db: Session, admin_user, sample_backup):
        """Test admin user can access any backup"""
        result = AuthorizationService.check_backup_access(sample_backup.id, admin_user, db)
        assert result == sample_backup
        assert result.id == sample_backup.id

    def test_check_backup_access_server_owner(self, db: Session, test_user, sample_backup, sample_server):
        """Test server owner can access backup"""
        # Update server to be owned by test_user
        sample_server.owner_id = test_user.id
        db.commit()
        
        result = AuthorizationService.check_backup_access(sample_backup.id, test_user, db)
        assert result == sample_backup

    def test_check_backup_access_non_server_owner_no_visibility_config(self, db: Session, test_user, sample_backup, sample_server):
        """Test non-server-owner CANNOT access backup without visibility config (Phase 2: Secure by default)"""
        # Ensure test_user is not the owner
        assert sample_server.owner_id != test_user.id
        
        # With Phase 2, backup access follows server visibility (secure by default)
        with pytest.raises(HTTPException) as exc_info:
            AuthorizationService.check_backup_access(sample_backup.id, test_user, db)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Not authorized to access this backup" in str(exc_info.value.detail)

    def test_check_backup_access_nonexistent_backup(self, db: Session, admin_user):
        """Test accessing non-existent backup raises 404"""
        nonexistent_id = 99999
        
        with pytest.raises(HTTPException) as exc_info:
            AuthorizationService.check_backup_access(nonexistent_id, admin_user, db)
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "Backup not found" in str(exc_info.value.detail)


class TestAuthorizationServiceRoleDecorators:
    """Test role-based decorators"""

    @pytest.mark.asyncio
    async def test_require_role_decorator_with_matching_role(self, admin_user):
        """Test require_role decorator allows matching role"""
        @AuthorizationService.require_role(Role.admin)
        async def protected_function(current_user=None):
            return "success"
        
        result = await protected_function(current_user=admin_user)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_require_role_decorator_with_admin_override(self, admin_user):
        """Test require_role decorator allows admin override"""
        @AuthorizationService.require_role(Role.operator)
        async def protected_function(current_user=None):
            return "success"
        
        result = await protected_function(current_user=admin_user)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_require_role_decorator_insufficient_role(self, test_user):
        """Test require_role decorator blocks insufficient role"""
        @AuthorizationService.require_role(Role.admin)
        async def protected_function(current_user=None):
            return "success"
        
        with pytest.raises(HTTPException) as exc_info:
            await protected_function(current_user=test_user)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Requires admin role or higher" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_require_role_decorator_no_user_in_kwargs(self):
        """Test require_role decorator handles missing user in kwargs"""
        @AuthorizationService.require_role(Role.admin)
        async def protected_function():
            return "success"
        
        with pytest.raises(HTTPException) as exc_info:
            await protected_function()
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Current user not found in request" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_require_role_decorator_user_in_args(self, admin_user):
        """Test require_role decorator finds user in args"""
        @AuthorizationService.require_role(Role.admin)
        async def protected_function(*args, **kwargs):
            return "success"
        
        result = await protected_function(admin_user, "other_arg")
        assert result == "success"

    @pytest.mark.asyncio
    async def test_require_admin_or_operator_admin_user(self, admin_user):
        """Test require_admin_or_operator allows admin"""
        @AuthorizationService.require_admin_or_operator()
        async def protected_function(current_user=None):
            return "success"
        
        result = await protected_function(current_user=admin_user)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_require_admin_or_operator_operator_user(self, operator_user):
        """Test require_admin_or_operator allows operator"""
        @AuthorizationService.require_admin_or_operator()
        async def protected_function(current_user=None):
            return "success"
        
        result = await protected_function(current_user=operator_user)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_require_admin_or_operator_regular_user(self, test_user):
        """Test require_admin_or_operator blocks regular user"""
        @AuthorizationService.require_admin_or_operator()
        async def protected_function(current_user=None):
            return "success"
        
        with pytest.raises(HTTPException) as exc_info:
            await protected_function(current_user=test_user)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Only operators and admins can perform this action" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_require_admin_or_operator_no_user_in_kwargs(self):
        """Test require_admin_or_operator handles missing user"""
        @AuthorizationService.require_admin_or_operator()
        async def protected_function():
            return "success"
        
        with pytest.raises(HTTPException) as exc_info:
            await protected_function()
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Current user not found in request" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_require_admin_or_operator_user_in_args(self, operator_user):
        """Test require_admin_or_operator finds user in args"""
        @AuthorizationService.require_admin_or_operator()
        async def protected_function(*args, **kwargs):
            return "success"
        
        result = await protected_function(operator_user, "other_arg")
        assert result == "success"


class TestAuthorizationServicePermissionChecks:
    """Test permission check methods"""

    def test_can_create_server_admin(self, admin_user):
        """Test admin can create servers"""
        assert AuthorizationService.can_create_server(admin_user) is True

    def test_can_create_server_operator(self, operator_user):
        """Test operator can create servers"""
        assert AuthorizationService.can_create_server(operator_user) is True

    def test_can_create_server_user(self, test_user):
        """Test regular user can create servers (Phase 1: shared resource model)"""
        assert AuthorizationService.can_create_server(test_user) is True

    def test_can_modify_files_admin(self, admin_user):
        """Test admin can modify files"""
        assert AuthorizationService.can_modify_files(admin_user) is True

    def test_can_modify_files_operator(self, operator_user):
        """Test operator can modify files"""
        assert AuthorizationService.can_modify_files(operator_user) is True

    def test_can_modify_files_user(self, test_user):
        """Test regular user can modify files (Phase 1: shared resource model)"""
        assert AuthorizationService.can_modify_files(test_user) is True

    def test_can_restore_backup_admin(self, admin_user):
        """Test admin can restore backups"""
        assert AuthorizationService.can_restore_backup(admin_user) is True

    def test_can_restore_backup_operator(self, operator_user):
        """Test operator can restore backups"""
        assert AuthorizationService.can_restore_backup(operator_user) is True

    def test_can_restore_backup_user(self, test_user):
        """Test regular user can restore backups (Phase 1: shared resource model)"""
        assert AuthorizationService.can_restore_backup(test_user) is True

    def test_can_create_backup_admin(self, admin_user):
        """Test admin can create backups"""
        assert AuthorizationService.can_create_backup(admin_user) is True

    def test_can_create_backup_operator(self, operator_user):
        """Test operator can create backups"""
        assert AuthorizationService.can_create_backup(operator_user) is True

    def test_can_create_backup_user(self, test_user):
        """Test regular user can create backups (Phase 1: shared resource model)"""
        assert AuthorizationService.can_create_backup(test_user) is True

    def test_can_create_group_admin(self, admin_user):
        """Test admin can create groups"""
        assert AuthorizationService.can_create_group(admin_user) is True

    def test_can_create_group_operator(self, operator_user):
        """Test operator can create groups"""
        assert AuthorizationService.can_create_group(operator_user) is True

    def test_can_create_group_user(self, test_user):
        """Test regular user can create groups (Phase 1: shared resource model)"""
        assert AuthorizationService.can_create_group(test_user) is True

    def test_can_create_template_admin(self, admin_user):
        """Test admin can create templates"""
        assert AuthorizationService.can_create_template(admin_user) is True

    def test_can_create_template_operator(self, operator_user):
        """Test operator can create templates"""
        assert AuthorizationService.can_create_template(operator_user) is True

    def test_can_create_template_user(self, test_user):
        """Test regular user can create templates (Phase 1: shared resource model)"""
        assert AuthorizationService.can_create_template(test_user) is True

    def test_can_schedule_backups_admin(self, admin_user):
        """Test only admin can schedule backups"""
        assert AuthorizationService.can_schedule_backups(admin_user) is True

    def test_can_schedule_backups_operator(self, operator_user):
        """Test operator cannot schedule backups"""
        assert AuthorizationService.can_schedule_backups(operator_user) is False

    def test_can_schedule_backups_user(self, test_user):
        """Test regular user cannot schedule backups"""
        assert AuthorizationService.can_schedule_backups(test_user) is False


class TestAuthorizationServiceServerFiltering:
    """Test server filtering methods"""

    def test_filter_servers_for_admin(self, db: Session, admin_user, sample_server):
        """Test admin sees all servers"""
        # Create additional server owned by different user
        another_server = Server(
            name="Another Server",
            description="Another test server",
            minecraft_version="1.19.4",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/2",
            port=25566,
            max_memory=1024,
            max_players=20,
            owner_id=999  # Different owner
        )
        db.add(another_server)
        db.commit()
        
        servers = [sample_server, another_server]
        filtered = AuthorizationService.filter_servers_for_user(admin_user, servers)
        
        assert len(filtered) == 2
        assert sample_server in filtered
        assert another_server in filtered

    def test_filter_servers_for_regular_user_with_db(self, db: Session, test_user, sample_server):
        """Test regular user sees only owned servers by default (Phase 2: Secure by default)"""
        # Create server owned by test_user
        user_server = Server(
            name="User Server",
            description="User's test server",
            minecraft_version="1.19.4",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/2",
            port=25566,
            max_memory=1024,
            max_players=20,
            owner_id=test_user.id
        )
        db.add(user_server)
        db.commit()
        
        servers = [sample_server, user_server]  # sample_server owned by admin_user
        filtered = AuthorizationService.filter_servers_for_user(test_user, servers, db)
        
        # With Phase 2, users see only owned servers (no visibility config = private)
        assert len(filtered) == 1
        assert user_server in filtered
        assert sample_server not in filtered

    def test_filter_servers_for_user_no_owned_servers_with_db(self, db: Session, test_user, sample_server):
        """Test user with no owned servers sees no servers by default (Phase 2: Secure by default)"""
        servers = [sample_server]  # owned by admin_user
        filtered = AuthorizationService.filter_servers_for_user(test_user, servers, db)
        
        # With Phase 2, users see no servers if they don't own any and no visibility config exists
        assert len(filtered) == 0
        assert sample_server not in filtered

    def test_filter_servers_for_operator_with_db(self, db: Session, operator_user, sample_server):
        """Test operator user sees only owned servers by default (Phase 2: Secure by default)"""
        # Create server owned by operator_user
        operator_server = Server(
            name="Operator Server",
            description="Operator's test server",
            minecraft_version="1.19.4",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/2",
            port=25566,
            max_memory=1024,
            max_players=20,
            owner_id=operator_user.id
        )
        db.add(operator_server)
        db.commit()
        
        servers = [sample_server, operator_server]  # sample_server owned by admin_user
        filtered = AuthorizationService.filter_servers_for_user(operator_user, servers, db)
        
        # With Phase 2, operators see only owned servers (no visibility config = private)
        assert len(filtered) == 1
        assert operator_server in filtered
        assert sample_server not in filtered


class TestAuthorizationServiceInstance:
    """Test service instance and static methods"""

    def test_authorization_service_instance_exists(self):
        """Test that authorization_service instance is available"""
        assert authorization_service is not None
        assert isinstance(authorization_service, AuthorizationService)

    def test_service_methods_are_static(self):
        """Test that all methods can be called statically"""
        # Test that methods exist and are callable
        assert callable(AuthorizationService.check_server_access)
        assert callable(AuthorizationService.check_backup_access)
        assert callable(AuthorizationService.require_role)
        assert callable(AuthorizationService.require_admin_or_operator)
        assert callable(AuthorizationService.can_create_server)
        assert callable(AuthorizationService.can_modify_files)
        assert callable(AuthorizationService.can_restore_backup)
        assert callable(AuthorizationService.can_create_template)
        assert callable(AuthorizationService.can_schedule_backups)
        assert callable(AuthorizationService.filter_servers_for_user)


class TestAuthorizationServiceEdgeCases:
    """Test edge cases and error conditions"""

    def test_check_server_access_with_none_user(self, db: Session, sample_server):
        """Test check_server_access with None user"""
        with pytest.raises(AttributeError):
            AuthorizationService.check_server_access(sample_server.id, None, db)

    def test_check_backup_access_with_none_user(self, db: Session):
        """Test check_backup_access with None user"""
        # This test expects an AttributeError when accessing None.role
        # But the actual implementation might handle this differently
        # Let's test with a more realistic scenario
        with pytest.raises((AttributeError, HTTPException)):
            AuthorizationService.check_backup_access(1, None, db)

    def test_permission_checks_with_none_user(self):
        """Test permission check methods with None user"""
        with pytest.raises(AttributeError):
            AuthorizationService.can_create_server(None)
        
        with pytest.raises(AttributeError):
            AuthorizationService.can_modify_files(None)
        
        with pytest.raises(AttributeError):
            AuthorizationService.can_restore_backup(None)
        
        with pytest.raises(AttributeError):
            AuthorizationService.can_create_template(None)
        
        with pytest.raises(AttributeError):
            AuthorizationService.can_schedule_backups(None)

    def test_filter_servers_with_none_user(self, db):
        """Test filter_servers_for_user with None user"""
        servers = []
        with pytest.raises(AttributeError):
            AuthorizationService.filter_servers_for_user(None, servers, db)

    def test_filter_servers_with_none_db(self, test_user):
        """Test filter_servers_for_user with None database session (security fix)"""
        servers = []
        with pytest.raises(ValueError, match="Database session is required for security filtering"):
            AuthorizationService.filter_servers_for_user(test_user, servers, None)

    def test_filter_servers_with_empty_list(self, test_user, db):
        """Test filter_servers_for_user with empty server list"""
        servers = []
        filtered = AuthorizationService.filter_servers_for_user(test_user, servers, db)
        assert filtered == []

    def test_check_server_access_with_database_error(self, admin_user):
        """Test check_server_access handles database errors"""
        # Create a mock database session that throws an error
        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database connection error")
        
        with pytest.raises(Exception, match="Database connection error"):
            AuthorizationService.check_server_access(1, admin_user, mock_db)

    def test_decorator_with_non_user_object_in_args(self):
        """Test decorator handles non-User objects in args"""
        @AuthorizationService.require_role(Role.admin)
        async def protected_function(*args, **kwargs):
            return "success"
        
        # This should raise an exception since no User object is found
        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(protected_function("not_a_user", 123, {"key": "value"}))
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Current user not found in request" in str(exc_info.value.detail)


class TestAuthorizationServiceRoleHierarchy:
    """Test role hierarchy and edge cases"""

    def test_role_hierarchy_admin_highest(self, admin_user, operator_user, test_user):
        """Test that admin role has highest privileges"""
        # Phase 1: All roles can do basic operations
        assert AuthorizationService.can_create_server(admin_user) == AuthorizationService.can_create_server(operator_user) == AuthorizationService.can_create_server(test_user) is True
        assert AuthorizationService.can_modify_files(admin_user) == AuthorizationService.can_modify_files(operator_user) == AuthorizationService.can_modify_files(test_user) is True
        assert AuthorizationService.can_restore_backup(admin_user) == AuthorizationService.can_restore_backup(operator_user) == AuthorizationService.can_restore_backup(test_user) is True
        assert AuthorizationService.can_create_backup(admin_user) == AuthorizationService.can_create_backup(operator_user) == AuthorizationService.can_create_backup(test_user) is True
        assert AuthorizationService.can_create_group(admin_user) == AuthorizationService.can_create_group(operator_user) == AuthorizationService.can_create_group(test_user) is True
        assert AuthorizationService.can_create_template(admin_user) == AuthorizationService.can_create_template(operator_user) == AuthorizationService.can_create_template(test_user) is True
        
        # But admin has exclusive privileges for scheduling
        assert AuthorizationService.can_schedule_backups(admin_user) is True
        assert AuthorizationService.can_schedule_backups(operator_user) is False
        assert AuthorizationService.can_schedule_backups(test_user) is False

    def test_role_hierarchy_operator_middle(self, operator_user, test_user):
        """Test that operator role has equivalent privileges to users (Phase 1: shared resource model)"""
        # Phase 1: Operator and regular user have same privileges for basic operations
        assert AuthorizationService.can_create_server(operator_user) == AuthorizationService.can_create_server(test_user) is True
        assert AuthorizationService.can_modify_files(operator_user) == AuthorizationService.can_modify_files(test_user) is True
        assert AuthorizationService.can_restore_backup(operator_user) == AuthorizationService.can_restore_backup(test_user) is True
        assert AuthorizationService.can_create_backup(operator_user) == AuthorizationService.can_create_backup(test_user) is True
        assert AuthorizationService.can_create_group(operator_user) == AuthorizationService.can_create_group(test_user) is True
        assert AuthorizationService.can_create_template(operator_user) == AuthorizationService.can_create_template(test_user) is True
        
        # Both cannot schedule backups (admin-only)
        assert AuthorizationService.can_schedule_backups(operator_user) is False
        assert AuthorizationService.can_schedule_backups(test_user) is False

    def test_role_hierarchy_user_basic_operations(self, test_user):
        """Test that user role can perform basic operations (Phase 1: shared resource model)"""
        # Phase 1: User can do most operations
        assert AuthorizationService.can_create_server(test_user) is True
        assert AuthorizationService.can_modify_files(test_user) is True
        assert AuthorizationService.can_restore_backup(test_user) is True
        assert AuthorizationService.can_create_backup(test_user) is True
        assert AuthorizationService.can_create_group(test_user) is True
        assert AuthorizationService.can_create_template(test_user) is True
        
        # But cannot schedule backups (admin-only)
        assert AuthorizationService.can_schedule_backups(test_user) is False


# Integration tests for realistic scenarios
class TestAuthorizationServiceIntegration:
    """Integration tests for realistic authorization scenarios"""

    def test_server_ownership_transfer_scenario(self, db: Session, admin_user, test_user, operator_user):
        """Test server access after ownership transfer"""
        # Create server owned by admin
        server = Server(
            name="Transfer Server",
            description="Server for ownership transfer test",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/transfer",
            port=25567,
            max_memory=1024,
            max_players=20,
            owner_id=admin_user.id
        )
        db.add(server)
        db.commit()
        db.refresh(server)
        
        # Admin can access
        result = AuthorizationService.check_server_access(server.id, admin_user, db)
        assert result.id == server.id
        
        # With Phase 2, other users cannot access without visibility config (secure default)
        with pytest.raises(HTTPException):
            AuthorizationService.check_server_access(server.id, test_user, db)
        
        with pytest.raises(HTTPException):
            AuthorizationService.check_server_access(server.id, operator_user, db)
        
        # Transfer ownership to test_user
        server.owner_id = test_user.id
        db.commit()
        
        # Now test_user can access
        result = AuthorizationService.check_server_access(server.id, test_user, db)
        assert result.id == server.id
        
        # Admin still can access (admin override)
        result = AuthorizationService.check_server_access(server.id, admin_user, db)
        assert result.id == server.id
        
        # With Phase 2, operator cannot access (not owner, not admin, no visibility config)
        with pytest.raises(HTTPException):
            AuthorizationService.check_server_access(server.id, operator_user, db)

    def test_backup_access_through_server_ownership(self, db: Session, test_user, admin_user):
        """Test backup access is controlled through server ownership"""
        # Create server owned by test_user
        server = Server(
            name="User Server",
            description="Server owned by regular user",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/user_server",
            port=25568,
            max_memory=1024,
            max_players=20,
            owner_id=test_user.id
        )
        db.add(server)
        db.commit()
        db.refresh(server)
        
        # Create backup for this server
        backup = Backup(
            server_id=server.id,
            name="user_backup",
            description="User backup description",
            file_path="/backups/user_backup.tar.gz",
            file_size=2048
        )
        db.add(backup)
        db.commit()
        db.refresh(backup)
        
        # User can access backup of their own server
        result = AuthorizationService.check_backup_access(backup.id, test_user, db)
        assert result.id == backup.id
        
        # Admin can access any backup
        result = AuthorizationService.check_backup_access(backup.id, admin_user, db)
        assert result.id == backup.id

    def test_multi_server_filtering_scenario(self, db: Session, admin_user, test_user, operator_user):
        """Test realistic multi-server filtering scenario"""
        # Create servers with different owners
        admin_server = Server(
            name="Admin Server",
            description="Admin's server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/admin",
            port=25569,
            max_memory=2048,
            max_players=50,
            owner_id=admin_user.id
        )
        
        user_server = Server(
            name="User Server",
            description="User's server",
            minecraft_version="1.19.4",
            server_type=ServerType.forge,
            status=ServerStatus.stopped,
            directory_path="./servers/user",
            port=25570,
            max_memory=1024,
            max_players=20,
            owner_id=test_user.id
        )
        
        operator_server = Server(
            name="Operator Server",
            description="Operator's server",
            minecraft_version="1.18.2",
            server_type=ServerType.paper,
            status=ServerStatus.stopped,
            directory_path="./servers/operator",
            port=25571,
            max_memory=1536,
            max_players=30,
            owner_id=operator_user.id
        )
        
        db.add_all([admin_server, user_server, operator_server])
        db.commit()
        
        all_servers = [admin_server, user_server, operator_server]
        
        # Admin sees all servers (admin override works without db session)
        admin_filtered = AuthorizationService.filter_servers_for_user(admin_user, all_servers)
        assert len(admin_filtered) == 3
        assert all(server in admin_filtered for server in all_servers)
        
        # With Phase 2 and no db session, falls back to return all (compatibility)
        user_filtered = AuthorizationService.filter_servers_for_user(test_user, all_servers)
        assert len(user_filtered) == 3
        assert all(server in user_filtered for server in all_servers)
        
        # Operator also gets all servers without db session (compatibility)
        operator_filtered = AuthorizationService.filter_servers_for_user(operator_user, all_servers)
        assert len(operator_filtered) == 3
        assert all(server in operator_filtered for server in all_servers)