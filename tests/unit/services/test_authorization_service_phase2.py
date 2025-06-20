"""
Tests for AuthorizationService Phase 2 visibility features

Tests the new visibility-based access control patterns:
- PUBLIC visibility (everyone can access)
- ROLE_BASED visibility (role hierarchy access)
- SPECIFIC_USERS visibility (explicit user grants)
"""

import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.visibility import (
    ResourceType,
    ResourceVisibility,
    ResourceUserAccess,
    VisibilityType,
)
from app.services.authorization_service import AuthorizationService
from app.users.models import Role, User


class TestAuthorizationServicePhase2Visibility:
    """Test Phase 2 visibility patterns in authorization service"""

    def test_check_server_access_with_public_visibility(
        self, db: Session, test_user, sample_server
    ):
        """Test non-owner can access server with PUBLIC visibility"""
        # Ensure test_user is not the owner
        assert sample_server.owner_id != test_user.id

        # Create PUBLIC visibility for the server
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=sample_server.id,
            visibility_type=VisibilityType.PUBLIC,
        )
        db.add(visibility)
        db.commit()

        # Now test_user should be able to access the server
        result = AuthorizationService.check_server_access(sample_server.id, test_user, db)
        assert result == sample_server
        assert result.id == sample_server.id

    def test_check_server_access_with_role_based_visibility_sufficient_role(
        self, db: Session, test_user, sample_server
    ):
        """Test user can access server with ROLE_BASED visibility when role is sufficient"""
        # Ensure test_user is not the owner
        assert sample_server.owner_id != test_user.id

        # Create ROLE_BASED visibility requiring 'user' role (test_user has 'user' role)
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=sample_server.id,
            visibility_type=VisibilityType.ROLE_BASED,
            role_restriction=Role.user,
        )
        db.add(visibility)
        db.commit()

        # test_user should be able to access the server
        result = AuthorizationService.check_server_access(sample_server.id, test_user, db)
        assert result == sample_server
        assert result.id == sample_server.id

    def test_check_server_access_with_role_based_visibility_insufficient_role(
        self, db: Session, test_user, sample_server
    ):
        """Test user cannot access server with ROLE_BASED visibility when role is insufficient"""
        # Ensure test_user is not the owner
        assert sample_server.owner_id != test_user.id

        # Create ROLE_BASED visibility requiring 'operator' role (test_user has 'user' role)
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=sample_server.id,
            visibility_type=VisibilityType.ROLE_BASED,
            role_restriction=Role.operator,
        )
        db.add(visibility)
        db.commit()

        # test_user should NOT be able to access the server
        with pytest.raises(HTTPException) as exc_info:
            AuthorizationService.check_server_access(sample_server.id, test_user, db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Not authorized to access this server" in str(exc_info.value.detail)

    def test_check_server_access_with_specific_users_visibility_granted(
        self, db: Session, test_user, sample_server
    ):
        """Test user can access server with SPECIFIC_USERS visibility when explicitly granted"""
        # Ensure test_user is not the owner
        assert sample_server.owner_id != test_user.id

        # Create SPECIFIC_USERS visibility
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=sample_server.id,
            visibility_type=VisibilityType.SPECIFIC_USERS,
        )
        db.add(visibility)
        db.commit()
        db.refresh(visibility)

        # Grant access to test_user
        access_grant = ResourceUserAccess(
            resource_visibility_id=visibility.id,
            user_id=test_user.id,
            granted_by_user_id=sample_server.owner_id,
        )
        db.add(access_grant)
        db.commit()

        # test_user should be able to access the server
        result = AuthorizationService.check_server_access(sample_server.id, test_user, db)
        assert result == sample_server
        assert result.id == sample_server.id

    def test_check_server_access_with_specific_users_visibility_not_granted(
        self, db: Session, test_user, sample_server
    ):
        """Test user cannot access server with SPECIFIC_USERS visibility when not explicitly granted"""
        # Ensure test_user is not the owner
        assert sample_server.owner_id != test_user.id

        # Create SPECIFIC_USERS visibility (no access grants)
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=sample_server.id,
            visibility_type=VisibilityType.SPECIFIC_USERS,
        )
        db.add(visibility)
        db.commit()

        # test_user should NOT be able to access the server
        with pytest.raises(HTTPException) as exc_info:
            AuthorizationService.check_server_access(sample_server.id, test_user, db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Not authorized to access this server" in str(exc_info.value.detail)

    def test_backup_access_follows_server_visibility(
        self, db: Session, test_user, sample_server
    ):
        """Test backup access follows server visibility configuration"""
        from app.servers.models import Backup

        # Create a backup for the server
        backup = Backup(
            server_id=sample_server.id,
            name="test_backup",
            description="Test backup",
            file_path="/backups/test.tar.gz",
            file_size=1024,
        )
        db.add(backup)
        db.commit()
        db.refresh(backup)

        # Ensure test_user is not the server owner
        assert sample_server.owner_id != test_user.id

        # Create PUBLIC visibility for the server
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=sample_server.id,
            visibility_type=VisibilityType.PUBLIC,
        )
        db.add(visibility)
        db.commit()

        # test_user should be able to access the backup (because server is public)
        result = AuthorizationService.check_backup_access(backup.id, test_user, db)
        assert result == backup
        assert result.id == backup.id

    def test_filter_servers_with_mixed_visibility(
        self, db: Session, test_user, admin_user
    ):
        """Test server filtering with mixed visibility configurations"""
        from app.servers.models import Server, ServerStatus, ServerType

        # Create multiple servers with different visibility
        public_server = Server(
            name="Public Server",
            description="Public test server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/public",
            port=25566,
            max_memory=1024,
            max_players=20,
            owner_id=999,  # Different owner
        )

        private_server = Server(
            name="Private Server",
            description="Private test server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/private",
            port=25567,
            max_memory=1024,
            max_players=20,
            owner_id=999,  # Different owner
        )

        role_server = Server(
            name="Role Server",
            description="Role-based test server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/role",
            port=25568,
            max_memory=1024,
            max_players=20,
            owner_id=999,  # Different owner
        )

        db.add_all([public_server, private_server, role_server])
        db.commit()
        db.refresh(public_server)
        db.refresh(private_server)
        db.refresh(role_server)

        # Set visibility configurations
        public_visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=public_server.id,
            visibility_type=VisibilityType.PUBLIC,
        )

        private_visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=private_server.id,
            visibility_type=VisibilityType.PRIVATE,
        )

        role_visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=role_server.id,
            visibility_type=VisibilityType.ROLE_BASED,
            role_restriction=Role.user,
        )

        db.add_all([public_visibility, private_visibility, role_visibility])
        db.commit()

        all_servers = [public_server, private_server, role_server]

        # Test regular user filtering
        filtered_servers = AuthorizationService.filter_servers_for_user(
            test_user, all_servers, db
        )
        filtered_ids = {server.id for server in filtered_servers}

        # test_user should see public and role servers, but not private
        assert public_server.id in filtered_ids
        assert role_server.id in filtered_ids  # test_user has 'user' role
        assert private_server.id not in filtered_ids

        # Test admin filtering
        admin_filtered_servers = AuthorizationService.filter_servers_for_user(
            admin_user, all_servers, db
        )
        admin_filtered_ids = {server.id for server in admin_filtered_servers}

        # Admin should see all servers
        assert len(admin_filtered_ids) == 3
        assert all(server.id in admin_filtered_ids for server in all_servers)

    def test_role_hierarchy_in_visibility(self, db: Session, sample_server):
        """Test role hierarchy works correctly with role-based visibility"""
        from passlib.context import CryptContext

        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        hashed_password = pwd_context.hash("testpassword")

        # Create users with different roles
        admin_user = User(
            username="admin_test",
            email="admin@test.com",
            hashed_password=hashed_password,
            role=Role.admin,
            is_approved=True,
        )

        operator_user = User(
            username="operator_test",
            email="operator@test.com",
            hashed_password=hashed_password,
            role=Role.operator,
            is_approved=True,
        )

        regular_user = User(
            username="regular_test",
            email="regular@test.com",
            hashed_password=hashed_password,
            role=Role.user,
            is_approved=True,
        )

        db.add_all([admin_user, operator_user, regular_user])
        db.commit()
        db.refresh(admin_user)
        db.refresh(operator_user)
        db.refresh(regular_user)

        # Ensure none of them own the server
        assert sample_server.owner_id not in [
            admin_user.id,
            operator_user.id,
            regular_user.id,
        ]

        # Create ROLE_BASED visibility requiring operator level
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=sample_server.id,
            visibility_type=VisibilityType.ROLE_BASED,
            role_restriction=Role.operator,
        )
        db.add(visibility)
        db.commit()

        # Test access for each role
        # Admin should have access (admin > operator)
        result = AuthorizationService.check_server_access(
            sample_server.id, admin_user, db
        )
        assert result.id == sample_server.id

        # Operator should have access (operator == operator)
        result = AuthorizationService.check_server_access(
            sample_server.id, operator_user, db
        )
        assert result.id == sample_server.id

        # Regular user should NOT have access (user < operator)
        with pytest.raises(HTTPException) as exc_info:
            AuthorizationService.check_server_access(sample_server.id, regular_user, db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
