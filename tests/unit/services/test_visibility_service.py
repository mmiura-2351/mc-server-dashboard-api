"""
Comprehensive tests for VisibilityService

Tests the Phase 2 visibility system with all visibility patterns:
- PRIVATE: Only owner + admins
- PUBLIC: Everyone
- ROLE_BASED: Users with certain roles + owner + admins
- SPECIFIC_USERS: Owner + specified users + admins
"""

import pytest

from app.core.visibility import (
    ResourceType,
    ResourceUserAccess,
    ResourceVisibility,
    VisibilityType,
)
from app.services.visibility_service import VisibilityService
from app.users.models import Role, User


class TestVisibilityServiceResourceAccess:
    """Test core resource access checking functionality"""

    @pytest.fixture
    def visibility_service(self, db):
        """Create visibility service instance"""
        return VisibilityService(db)

    @pytest.fixture
    def sample_resource_visibility(self, db):
        """Create sample resource visibility configuration"""
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.PUBLIC,
        )
        db.add(visibility)
        db.commit()
        db.refresh(visibility)
        return visibility

    def test_admin_access_override(self, visibility_service, admin_user):
        """Test that admins can access any resource regardless of visibility"""
        # Admin should have access even without visibility config
        has_access = visibility_service.check_resource_access(
            user=admin_user,
            resource_type=ResourceType.SERVER,
            resource_id=999,  # Non-existent resource
            resource_owner_id=123,
        )
        assert has_access is True

    def test_owner_access_override(self, visibility_service, test_user):
        """Test that owners can access their resources regardless of visibility"""
        # Owner should have access even without visibility config
        has_access = visibility_service.check_resource_access(
            user=test_user,
            resource_type=ResourceType.SERVER,
            resource_id=1,
            resource_owner_id=test_user.id,
        )
        assert has_access is True

    def test_public_visibility_access(
        self, visibility_service, test_user, sample_resource_visibility
    ):
        """Test that anyone can access PUBLIC resources"""
        # Update to public visibility
        sample_resource_visibility.visibility_type = VisibilityType.PUBLIC
        visibility_service.db.commit()

        has_access = visibility_service.check_resource_access(
            user=test_user,
            resource_type=ResourceType.SERVER,
            resource_id=1,
            resource_owner_id=999,  # Different owner
        )
        assert has_access is True

    def test_private_visibility_access_denied(
        self, visibility_service, test_user, sample_resource_visibility
    ):
        """Test that non-owners/non-admins cannot access PRIVATE resources"""
        # Update to private visibility
        sample_resource_visibility.visibility_type = VisibilityType.PRIVATE
        visibility_service.db.commit()

        has_access = visibility_service.check_resource_access(
            user=test_user,
            resource_type=ResourceType.SERVER,
            resource_id=1,
            resource_owner_id=999,  # Different owner
        )
        assert has_access is False

    def test_role_based_visibility_user_access(
        self, visibility_service, test_user, sample_resource_visibility
    ):
        """Test role-based visibility with user role requirement"""
        # Update to role-based visibility with user role requirement
        sample_resource_visibility.visibility_type = VisibilityType.ROLE_BASED
        sample_resource_visibility.role_restriction = Role.user
        visibility_service.db.commit()

        has_access = visibility_service.check_resource_access(
            user=test_user,  # test_user has 'user' role
            resource_type=ResourceType.SERVER,
            resource_id=1,
            resource_owner_id=999,  # Different owner
        )
        assert has_access is True

    def test_role_based_visibility_operator_access(
        self, visibility_service, test_user, sample_resource_visibility
    ):
        """Test role-based visibility with operator role requirement (should deny user)"""
        # Update to role-based visibility with operator role requirement
        sample_resource_visibility.visibility_type = VisibilityType.ROLE_BASED
        sample_resource_visibility.role_restriction = Role.operator
        visibility_service.db.commit()

        has_access = visibility_service.check_resource_access(
            user=test_user,  # test_user has 'user' role (insufficient)
            resource_type=ResourceType.SERVER,
            resource_id=1,
            resource_owner_id=999,  # Different owner
        )
        assert has_access is False

    def test_role_based_visibility_no_restriction(
        self, visibility_service, test_user, sample_resource_visibility
    ):
        """Test role-based visibility with no role restriction"""
        # Update to role-based visibility with no role restriction
        sample_resource_visibility.visibility_type = VisibilityType.ROLE_BASED
        sample_resource_visibility.role_restriction = None
        visibility_service.db.commit()

        has_access = visibility_service.check_resource_access(
            user=test_user,
            resource_type=ResourceType.SERVER,
            resource_id=1,
            resource_owner_id=999,  # Different owner
        )
        assert has_access is True

    def test_specific_users_visibility_granted_access(
        self, visibility_service, test_user, sample_resource_visibility
    ):
        """Test specific users visibility with granted access"""
        # Update to specific users visibility
        sample_resource_visibility.visibility_type = VisibilityType.SPECIFIC_USERS
        visibility_service.db.commit()

        # Grant access to test_user
        access_grant = ResourceUserAccess(
            resource_visibility_id=sample_resource_visibility.id,
            user_id=test_user.id,
            granted_by_user_id=999,
        )
        visibility_service.db.add(access_grant)
        visibility_service.db.commit()

        has_access = visibility_service.check_resource_access(
            user=test_user,
            resource_type=ResourceType.SERVER,
            resource_id=1,
            resource_owner_id=999,  # Different owner
        )
        assert has_access is True

    def test_specific_users_visibility_no_grant_access_denied(
        self, visibility_service, test_user, sample_resource_visibility
    ):
        """Test specific users visibility without granted access"""
        # Update to specific users visibility
        sample_resource_visibility.visibility_type = VisibilityType.SPECIFIC_USERS
        visibility_service.db.commit()

        # No access grant for test_user
        has_access = visibility_service.check_resource_access(
            user=test_user,
            resource_type=ResourceType.SERVER,
            resource_id=1,
            resource_owner_id=999,  # Different owner
        )
        assert has_access is False

    def test_no_visibility_config_defaults_to_private(
        self, visibility_service, test_user
    ):
        """Test that resources without visibility config default to private access"""
        has_access = visibility_service.check_resource_access(
            user=test_user,
            resource_type=ResourceType.SERVER,
            resource_id=999,  # No visibility config
            resource_owner_id=999,  # Different owner
        )
        assert has_access is False


class TestVisibilityServiceResourceFiltering:
    """Test resource filtering functionality"""

    @pytest.fixture
    def visibility_service(self, db):
        """Create visibility service instance"""
        return VisibilityService(db)

    def test_filter_resources_by_visibility_public(
        self, visibility_service, test_user, db
    ):
        """Test filtering resources with public visibility"""
        # Create public visibility for server 1
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.PUBLIC,
        )
        db.add(visibility)
        db.commit()

        resources = [(1, 999), (2, 999)]  # Two servers, both owned by user 999
        accessible_ids = visibility_service.filter_resources_by_visibility(
            user=test_user, resources=resources, resource_type=ResourceType.SERVER
        )

        # Should only see server 1 (public), not server 2 (no config = private)
        assert accessible_ids == [1]

    def test_filter_resources_by_visibility_owner(
        self, visibility_service, test_user, db
    ):
        """Test filtering resources as owner"""
        resources = [(1, test_user.id), (2, 999)]  # test_user owns server 1, not server 2
        accessible_ids = visibility_service.filter_resources_by_visibility(
            user=test_user, resources=resources, resource_type=ResourceType.SERVER
        )

        # Should see server 1 (owned), not server 2 (not owned, no config = private)
        assert accessible_ids == [1]

    def test_filter_resources_by_visibility_admin(self, visibility_service, admin_user):
        """Test filtering resources as admin"""
        resources = [(1, 999), (2, 888)]  # Admin doesn't own either
        accessible_ids = visibility_service.filter_resources_by_visibility(
            user=admin_user, resources=resources, resource_type=ResourceType.SERVER
        )

        # Admin should see all resources
        assert set(accessible_ids) == {1, 2}


class TestVisibilityServiceManagement:
    """Test visibility configuration management"""

    @pytest.fixture
    def visibility_service(self, db):
        """Create visibility service instance"""
        return VisibilityService(db)

    def test_set_resource_visibility_new(self, visibility_service):
        """Test setting visibility for new resource"""
        visibility = visibility_service.set_resource_visibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.PRIVATE,
            requesting_user_id=123,
        )

        assert visibility.resource_type == ResourceType.SERVER
        assert visibility.resource_id == 1
        assert visibility.visibility_type == VisibilityType.PRIVATE

    def test_set_resource_visibility_update_existing(self, visibility_service, db):
        """Test updating existing visibility configuration"""
        # Create initial visibility
        initial_visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.PUBLIC,
        )
        db.add(initial_visibility)
        db.commit()

        # Update visibility
        updated_visibility = visibility_service.set_resource_visibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.PRIVATE,
            requesting_user_id=123,
        )

        assert updated_visibility.id == initial_visibility.id
        assert updated_visibility.visibility_type == VisibilityType.PRIVATE

    def test_set_resource_visibility_clears_user_grants(
        self, visibility_service, test_user, db
    ):
        """Test that changing away from SPECIFIC_USERS clears user grants"""
        # Create specific users visibility
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.SPECIFIC_USERS,
        )
        db.add(visibility)
        db.commit()
        db.refresh(visibility)

        # Add user grant
        access_grant = ResourceUserAccess(
            resource_visibility_id=visibility.id,
            user_id=test_user.id,
            granted_by_user_id=999,
        )
        db.add(access_grant)
        db.commit()

        # Change to public visibility
        visibility_service.set_resource_visibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.PUBLIC,
        )

        # Check that user grants were cleared
        remaining_grants = (
            db.query(ResourceUserAccess)
            .filter(ResourceUserAccess.resource_visibility_id == visibility.id)
            .count()
        )
        assert remaining_grants == 0

    def test_grant_user_access_success(self, visibility_service, test_user, db):
        """Test granting user access to resource"""
        # Create specific users visibility
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.SPECIFIC_USERS,
        )
        db.add(visibility)
        db.commit()

        # Grant access
        access_grant = visibility_service.grant_user_access(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            user_id=test_user.id,
            granted_by_user_id=999,
        )

        assert access_grant.user_id == test_user.id
        assert access_grant.granted_by_user_id == 999

    def test_grant_user_access_wrong_visibility_type(
        self, visibility_service, test_user, db
    ):
        """Test granting user access to resource with wrong visibility type"""
        # Create public visibility (not specific users)
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.PUBLIC,
        )
        db.add(visibility)
        db.commit()

        # Try to grant access (should fail)
        with pytest.raises(Exception) as exc_info:
            visibility_service.grant_user_access(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                user_id=test_user.id,
                granted_by_user_id=999,
            )

        assert "SPECIFIC_USERS visibility type" in str(exc_info.value)

    def test_grant_user_access_already_granted(self, visibility_service, test_user, db):
        """Test granting access to user who already has access"""
        # Create specific users visibility
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.SPECIFIC_USERS,
        )
        db.add(visibility)
        db.commit()
        db.refresh(visibility)

        # Grant initial access
        access_grant = ResourceUserAccess(
            resource_visibility_id=visibility.id,
            user_id=test_user.id,
            granted_by_user_id=999,
        )
        db.add(access_grant)
        db.commit()

        # Try to grant access again (should fail)
        with pytest.raises(Exception) as exc_info:
            visibility_service.grant_user_access(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                user_id=test_user.id,
                granted_by_user_id=999,
            )

        assert "already has access" in str(exc_info.value)

    def test_revoke_user_access_success(self, visibility_service, test_user, db):
        """Test revoking user access from resource"""
        # Create specific users visibility with access grant
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.SPECIFIC_USERS,
        )
        db.add(visibility)
        db.commit()
        db.refresh(visibility)

        access_grant = ResourceUserAccess(
            resource_visibility_id=visibility.id,
            user_id=test_user.id,
            granted_by_user_id=999,
        )
        db.add(access_grant)
        db.commit()

        # Revoke access
        revoked = visibility_service.revoke_user_access(
            resource_type=ResourceType.SERVER, resource_id=1, user_id=test_user.id
        )

        assert revoked is True

        # Verify access was removed
        remaining_grants = (
            db.query(ResourceUserAccess)
            .filter(
                ResourceUserAccess.resource_visibility_id == visibility.id,
                ResourceUserAccess.user_id == test_user.id,
            )
            .count()
        )
        assert remaining_grants == 0

    def test_revoke_user_access_not_found(self, visibility_service, test_user):
        """Test revoking access from user who doesn't have access"""
        revoked = visibility_service.revoke_user_access(
            resource_type=ResourceType.SERVER,
            resource_id=999,  # Non-existent resource
            user_id=test_user.id,
        )

        assert revoked is False

    def test_get_resource_visibility_info_public(self, visibility_service, db):
        """Test getting visibility info for public resource"""
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.PUBLIC,
        )
        db.add(visibility)
        db.commit()

        info = visibility_service.get_resource_visibility_info(ResourceType.SERVER, 1)

        assert info is not None
        assert info["visibility_type"] == "public"
        assert info["role_restriction"] is None
        assert "granted_users" not in info  # Not included for non-specific_users

    def test_get_resource_visibility_info_specific_users(
        self, visibility_service, test_user, db
    ):
        """Test getting visibility info for specific users resource"""
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.SPECIFIC_USERS,
        )
        db.add(visibility)
        db.commit()
        db.refresh(visibility)

        # Add access grant
        access_grant = ResourceUserAccess(
            resource_visibility_id=visibility.id,
            user_id=test_user.id,
            granted_by_user_id=999,
        )
        db.add(access_grant)
        db.commit()

        info = visibility_service.get_resource_visibility_info(ResourceType.SERVER, 1)

        assert info is not None
        assert info["visibility_type"] == "specific_users"
        assert "granted_users" in info
        assert len(info["granted_users"]) == 1
        assert info["granted_users"][0]["user_id"] == test_user.id

    def test_get_resource_visibility_info_not_found(self, visibility_service):
        """Test getting visibility info for non-existent resource"""
        info = visibility_service.get_resource_visibility_info(ResourceType.SERVER, 999)

        assert info is None


# Additional edge case tests
class TestVisibilityServiceEdgeCases:
    """Test edge cases and error conditions"""

    @pytest.fixture
    def visibility_service(self, db):
        """Create visibility service instance"""
        return VisibilityService(db)

    def test_unknown_visibility_type_handling(self, visibility_service, test_user, db):
        """Test handling of unknown visibility types"""
        # Create visibility with invalid type (simulating future enum additions)
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.PUBLIC,  # We'll mock this
        )
        db.add(visibility)
        db.commit()

        # Mock unknown visibility type
        visibility.visibility_type = (
            "unknown_type"  # This would fail enum validation in real scenario
        )

        # The service should handle this gracefully by defaulting to deny access
        # Note: In practice, this would be caught by enum validation, but testing the fallback
        # We can't easily test this without mocking, so we'll test the actual enum validation instead

        # Test with actual enum value - should be denied due to unknown visibility type
        has_access = visibility_service.check_resource_access(
            user=test_user,
            resource_type=ResourceType.SERVER,
            resource_id=1,
            resource_owner_id=999,
        )
        assert (
            has_access is False
        )  # Should deny access with unknown visibility type (secure default)

    def test_role_hierarchy_edge_cases(self, visibility_service, db):
        """Test role hierarchy edge cases"""
        from app.users.models import Role

        # Create users with different roles
        admin_user = User(id=1, role=Role.admin, username="admin", email="admin@test.com")
        operator_user = User(
            id=2, role=Role.operator, username="operator", email="operator@test.com"
        )
        regular_user = User(id=3, role=Role.user, username="user", email="user@test.com")

        # Create role-based visibility requiring operator level
        visibility = ResourceVisibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.ROLE_BASED,
            role_restriction=Role.operator,
        )
        db.add(visibility)
        db.commit()

        # Test role hierarchy
        assert (
            visibility_service.check_resource_access(
                admin_user, ResourceType.SERVER, 1, 999
            )
            is True
        )
        assert (
            visibility_service.check_resource_access(
                operator_user, ResourceType.SERVER, 1, 999
            )
            is True
        )
        assert (
            visibility_service.check_resource_access(
                regular_user, ResourceType.SERVER, 1, 999
            )
            is False
        )

    def test_empty_resource_list_filtering(self, visibility_service, test_user):
        """Test filtering empty resource list"""
        accessible_ids = visibility_service.filter_resources_by_visibility(
            user=test_user, resources=[], resource_type=ResourceType.SERVER
        )

        assert accessible_ids == []

    def test_malformed_resource_tuples(self, visibility_service, test_user):
        """Test handling of malformed resource tuples"""
        # This should be handled gracefully by the service
        resources = [(1, 999), (2, None), (3, 888)]  # One with None owner_id

        # The service should handle None owner_id gracefully
        accessible_ids = visibility_service.filter_resources_by_visibility(
            user=test_user, resources=resources, resource_type=ResourceType.SERVER
        )

        # Should not crash and should return valid accessible IDs
        assert isinstance(accessible_ids, list)
