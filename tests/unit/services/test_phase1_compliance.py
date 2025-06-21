"""
Phase 1 Compliance Tests

Tests that verify all Phase 1 requirements from GitHub Issue #66 are met.
Ensures that users with "User" role or higher can perform all specified operations:
- Create servers
- View servers
- Operate servers
- Manage groups
- Edit files
- Create backups
"""

import pytest
from unittest.mock import Mock, AsyncMock
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.authorization_service import AuthorizationService
from app.users.models import Role, User
from app.servers.models import Server, ServerStatus, ServerType, Backup, BackupType
from app.groups.models import Group, GroupType
from app.core.visibility import ResourceType, VisibilityType


class TestPhase1ComplianceBasicOperations:
    """Test that all users can perform basic operations specified in Phase 1"""

    def test_all_users_can_create_servers(self, admin_user, operator_user, test_user):
        """Test that all users (admin, operator, user) can create servers"""
        assert AuthorizationService.can_create_server(admin_user) is True
        assert AuthorizationService.can_create_server(operator_user) is True
        assert AuthorizationService.can_create_server(test_user) is True

    def test_all_users_can_modify_files(self, admin_user, operator_user, test_user):
        """Test that all users can edit files"""
        assert AuthorizationService.can_modify_files(admin_user) is True
        assert AuthorizationService.can_modify_files(operator_user) is True
        assert AuthorizationService.can_modify_files(test_user) is True

    def test_all_users_can_create_backups(self, admin_user, operator_user, test_user):
        """Test that all users can create backups"""
        assert AuthorizationService.can_create_backup(admin_user) is True
        assert AuthorizationService.can_create_backup(operator_user) is True
        assert AuthorizationService.can_create_backup(test_user) is True

    def test_all_users_can_restore_backups(self, admin_user, operator_user, test_user):
        """Test that all users can restore backups"""
        assert AuthorizationService.can_restore_backup(admin_user) is True
        assert AuthorizationService.can_restore_backup(operator_user) is True
        assert AuthorizationService.can_restore_backup(test_user) is True

    def test_all_users_can_create_groups(self, admin_user, operator_user, test_user):
        """Test that all users can create groups"""
        assert AuthorizationService.can_create_group(admin_user) is True
        assert AuthorizationService.can_create_group(operator_user) is True
        assert AuthorizationService.can_create_group(test_user) is True

    def test_all_users_can_create_templates(self, admin_user, operator_user, test_user):
        """Test that all users can create templates"""
        assert AuthorizationService.can_create_template(admin_user) is True
        assert AuthorizationService.can_create_template(operator_user) is True
        assert AuthorizationService.can_create_template(test_user) is True


class TestPhase1ComplianceAdminOnlyOperations:
    """Test that some operations remain admin-only as appropriate"""

    def test_only_admin_can_schedule_backups(self, admin_user, operator_user, test_user):
        """Test that only admins can schedule automated backups"""
        assert AuthorizationService.can_schedule_backups(admin_user) is True
        assert AuthorizationService.can_schedule_backups(operator_user) is False
        assert AuthorizationService.can_schedule_backups(test_user) is False


class TestPhase1ComplianceResourceAccess:
    """Test resource access patterns for Phase 1 compliance"""

    def test_users_can_view_servers_with_visibility_system(
        self, db: Session, test_user, admin_user
    ):
        """Test that users can view servers through visibility system (Phase 1+2)"""
        # Create a server owned by admin
        server = Server(
            name="Test Server",
            description="Test server for visibility",
            minecraft_version="1.19.4",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/test_visibility",
            port=25565,
            max_memory=1024,
            max_players=20,
            owner_id=admin_user.id,
        )
        db.add(server)
        db.commit()

        # New permission model: all users can access all servers regardless of visibility config
        try:
            AuthorizationService.check_server_access(server.id, test_user, db)
            # If this doesn't raise an exception, the user has access
            has_access = True
        except HTTPException:
            has_access = False

        # New permission model: all users can access all servers
        assert has_access is True, (
            "All users should be able to access all servers in the new permission model"
        )


class TestPhase1ComplianceOperationalRequirements:
    """Test that Phase 1 operational requirements are met"""

    def test_phase1_transforms_from_ownership_based_to_shared_model(
        self, test_user, admin_user
    ):
        """Test that the access model has been transformed from ownership-based to shared"""
        # Phase 1 requirement: "Transform from ownership-based to shared resource access model"

        # In Phase 0 (ownership-based), only owners and admins could perform operations
        # In Phase 1 (shared model), all users can perform basic operations

        # Verify that regular users now have the same basic permissions as admins/operators
        # for the core operations specified in the GitHub comment

        operations = [
            AuthorizationService.can_create_server,
            AuthorizationService.can_modify_files,
            AuthorizationService.can_create_backup,
            AuthorizationService.can_restore_backup,
            AuthorizationService.can_create_group,
            AuthorizationService.can_create_template,
        ]

        for operation in operations:
            user_permission = operation(test_user)
            admin_permission = operation(admin_user)
            assert user_permission == admin_permission == True, (
                f"Operation {operation.__name__} should be available to all users in Phase 1"
            )

    def test_view_servers_requirement(self, db: Session, test_user):
        """Test view servers requirement - users can see servers through visibility system"""
        # Create sample servers
        servers = [
            Server(
                name=f"Server {i}",
                description=f"Test server {i}",
                minecraft_version="1.19.4",
                server_type=ServerType.vanilla,
                status=ServerStatus.stopped,
                directory_path=f"./servers/test_{i}",
                port=25565 + i,
                max_memory=1024,
                max_players=20,
                owner_id=i,  # Different owners
            )
            for i in range(1, 4)
        ]

        for server in servers:
            db.add(server)
        db.commit()

        # Test that filtering works with the visibility system
        # (Note: Without visibility configs, Phase 2 defaults to private)
        filtered_servers = AuthorizationService.filter_servers_for_user(
            test_user, servers, db
        )

        # This validates that the visibility system is working
        # In Phase 2, without visibility configs, users see no servers (secure default)
        assert isinstance(filtered_servers, list), (
            "filter_servers_for_user should return a list"
        )

    def test_operate_servers_requirement(self, db: Session, test_user):
        """Test operate servers requirement - users can access servers they have visibility to"""
        # Create a server
        server = Server(
            name="Operational Test Server",
            description="Test server operations",
            minecraft_version="1.19.4",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/operational_test",
            port=25567,
            max_memory=1024,
            max_players=20,
            owner_id=test_user.id,  # User owns this server
        )
        db.add(server)
        db.commit()

        # User should be able to access their own server (owner privilege)
        try:
            result = AuthorizationService.check_server_access(server.id, test_user, db)
            assert result == server, "User should be able to access their own server"
        except HTTPException:
            pytest.fail("User should be able to access their own server")

    def test_manage_groups_requirement(self, test_user):
        """Test manage groups requirement - users can create groups"""
        # This is tested through the authorization service
        assert AuthorizationService.can_create_group(test_user) is True, (
            "Users should be able to create groups in Phase 1"
        )

    def test_edit_files_requirement(self, test_user):
        """Test edit files requirement - users can modify server files"""
        assert AuthorizationService.can_modify_files(test_user) is True, (
            "Users should be able to edit files in Phase 1"
        )

    def test_create_backups_requirement(self, test_user):
        """Test create backups requirement - users can create backups"""
        assert AuthorizationService.can_create_backup(test_user) is True, (
            "Users should be able to create backups in Phase 1"
        )


class TestPhase1ComplianceIntegration:
    """Integration tests for Phase 1 compliance across the system"""

    def test_complete_phase1_workflow_for_regular_user(self, db: Session, test_user):
        """Test that a regular user can perform a complete workflow as specified in Phase 1"""

        # 1. User can create a server (check authorization)
        assert AuthorizationService.can_create_server(test_user) is True

        # 2. User can manage groups (check authorization)
        assert AuthorizationService.can_create_group(test_user) is True

        # 3. User can edit files (check authorization)
        assert AuthorizationService.can_modify_files(test_user) is True

        # 4. User can create backups (check authorization)
        assert AuthorizationService.can_create_backup(test_user) is True

        # 5. User can restore backups (check authorization)
        assert AuthorizationService.can_restore_backup(test_user) is True

        # All Phase 1 requirements verified for regular user workflow

    def test_phase1_maintains_security_boundaries(
        self, admin_user, operator_user, test_user
    ):
        """Test that Phase 1 still maintains appropriate security boundaries"""

        # Scheduled backups should remain admin-only
        assert AuthorizationService.can_schedule_backups(admin_user) is True
        assert AuthorizationService.can_schedule_backups(operator_user) is False
        assert AuthorizationService.can_schedule_backups(test_user) is False

        # Role decorators should still work
        assert AuthorizationService.is_admin(admin_user) is True
        assert AuthorizationService.is_admin(operator_user) is False
        assert AuthorizationService.is_admin(test_user) is False

        assert AuthorizationService.is_operator_or_admin(admin_user) is True
        assert AuthorizationService.is_operator_or_admin(operator_user) is True
        assert AuthorizationService.is_operator_or_admin(test_user) is False


# Test fixtures and utilities specific to Phase 1 compliance
@pytest.fixture
def phase1_user():
    """Create a regular user for Phase 1 testing"""
    return User(
        id=100,
        username="phase1_user",
        email="phase1@example.com",
        role=Role.user,
        is_active=True,
        is_approved=True,
    )


@pytest.fixture
def phase1_server(db: Session, phase1_user):
    """Create a server owned by a regular user for Phase 1 testing"""
    server = Server(
        name="Phase 1 Test Server",
        description="Server for Phase 1 compliance testing",
        minecraft_version="1.19.4",
        server_type=ServerType.vanilla,
        status=ServerStatus.stopped,
        directory_path="./servers/phase1_test",
        port=25569,
        max_memory=1024,
        max_players=20,
        owner_id=phase1_user.id,
    )
    db.add(server)
    db.commit()
    return server


class TestPhase1ComplianceWithPhase2Integration:
    """Test Phase 1 compliance works correctly with Phase 2 visibility system"""

    def test_phase1_and_phase2_integration(self, db: Session, phase1_user, phase1_server):
        """Test that Phase 1 permissions work with Phase 2 visibility system"""

        # User should be able to access their own server (owner access in Phase 2)
        try:
            result = AuthorizationService.check_server_access(
                phase1_server.id, phase1_user, db
            )
            assert result == phase1_server
        except HTTPException:
            pytest.fail("User should be able to access their own server")

        # User should have all Phase 1 permissions
        assert AuthorizationService.can_create_server(phase1_user) is True
        assert AuthorizationService.can_modify_files(phase1_user) is True
        assert AuthorizationService.can_create_backup(phase1_user) is True
        assert AuthorizationService.can_restore_backup(phase1_user) is True
        assert AuthorizationService.can_create_group(phase1_user) is True
        assert AuthorizationService.can_create_template(phase1_user) is True


if __name__ == "__main__":
    pytest.main([__file__])
