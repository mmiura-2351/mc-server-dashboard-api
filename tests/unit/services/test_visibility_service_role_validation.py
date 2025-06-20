"""
Tests for Role Hierarchy Validation in Visibility Service

Tests the new role validation functionality added to fix GitHub PR review issues.
Ensures role restrictions are logically consistent with visibility types.
"""

import pytest
from sqlalchemy.orm import Session

from app.core.visibility import ResourceType, VisibilityType
from app.services.visibility_service import VisibilityService
from app.users.models import Role


class TestVisibilityServiceRoleValidation:
    """Test role hierarchy validation in visibility service"""

    def test_role_based_visibility_with_valid_roles(self, db: Session):
        """Test ROLE_BASED visibility accepts valid role restrictions"""
        service = VisibilityService(db)

        # Test all valid roles
        for role in [Role.user, Role.operator, Role.admin]:
            # Should not raise exception
            service._validate_role_configuration(VisibilityType.ROLE_BASED, role)

    def test_role_based_visibility_without_role_restriction(self, db: Session):
        """Test ROLE_BASED visibility allows None role (defaults to all users)"""
        service = VisibilityService(db)

        # Should not raise exception, just log warning
        service._validate_role_configuration(VisibilityType.ROLE_BASED, None)

    def test_non_role_based_visibility_rejects_role_restrictions(self, db: Session):
        """Test other visibility types reject role restrictions"""
        service = VisibilityService(db)

        # Test specific error messages for each visibility type
        private_combinations = [
            (VisibilityType.PRIVATE, Role.user),
            (VisibilityType.PRIVATE, Role.operator),
            (VisibilityType.PRIVATE, Role.admin),
        ]

        for visibility_type, role in private_combinations:
            with pytest.raises(
                ValueError, match="PRIVATE visibility cannot have role restrictions"
            ):
                service._validate_role_configuration(visibility_type, role)

        public_combinations = [
            (VisibilityType.PUBLIC, Role.user),
            (VisibilityType.PUBLIC, Role.operator),
            (VisibilityType.PUBLIC, Role.admin),
        ]

        for visibility_type, role in public_combinations:
            with pytest.raises(
                ValueError, match="PUBLIC visibility cannot have role restrictions"
            ):
                service._validate_role_configuration(visibility_type, role)

        specific_users_combinations = [
            (VisibilityType.SPECIFIC_USERS, Role.user),
            (VisibilityType.SPECIFIC_USERS, Role.operator),
            (VisibilityType.SPECIFIC_USERS, Role.admin),
        ]

        for visibility_type, role in specific_users_combinations:
            with pytest.raises(
                ValueError,
                match="SPECIFIC_USERS visibility cannot have role restrictions",
            ):
                service._validate_role_configuration(visibility_type, role)

    def test_private_visibility_specific_error_message(self, db: Session):
        """Test PRIVATE visibility gives specific error for role restrictions"""
        service = VisibilityService(db)

        with pytest.raises(
            ValueError, match="PRIVATE visibility cannot have role restrictions"
        ):
            service._validate_role_configuration(VisibilityType.PRIVATE, Role.user)

    def test_public_visibility_specific_error_message(self, db: Session):
        """Test PUBLIC visibility gives specific error for role restrictions"""
        service = VisibilityService(db)

        with pytest.raises(
            ValueError, match="PUBLIC visibility cannot have role restrictions"
        ):
            service._validate_role_configuration(VisibilityType.PUBLIC, Role.user)

    def test_specific_users_visibility_specific_error_message(self, db: Session):
        """Test SPECIFIC_USERS visibility gives specific error for role restrictions"""
        service = VisibilityService(db)

        with pytest.raises(
            ValueError, match="SPECIFIC_USERS visibility cannot have role restrictions"
        ):
            service._validate_role_configuration(VisibilityType.SPECIFIC_USERS, Role.user)

    def test_set_resource_visibility_validates_roles(self, db: Session):
        """Test set_resource_visibility integrates role validation"""
        service = VisibilityService(db)

        # Valid configuration should work
        visibility = service.set_resource_visibility(
            resource_type=ResourceType.SERVER,
            resource_id=1,
            visibility_type=VisibilityType.ROLE_BASED,
            role_restriction=Role.operator,
        )
        assert visibility.visibility_type == VisibilityType.ROLE_BASED
        assert visibility.role_restriction == Role.operator

        # Invalid configuration should fail
        with pytest.raises(
            ValueError, match="PUBLIC visibility cannot have role restrictions"
        ):
            service.set_resource_visibility(
                resource_type=ResourceType.SERVER,
                resource_id=2,
                visibility_type=VisibilityType.PUBLIC,
                role_restriction=Role.admin,  # Invalid for PUBLIC
            )

    def test_role_hierarchy_validation_comprehensive(self, db: Session):
        """Test comprehensive role hierarchy validation scenarios"""
        service = VisibilityService(db)

        # Test all valid ROLE_BASED configurations
        valid_configs = [
            (VisibilityType.ROLE_BASED, None),
            (VisibilityType.ROLE_BASED, Role.user),
            (VisibilityType.ROLE_BASED, Role.operator),
            (VisibilityType.ROLE_BASED, Role.admin),
        ]

        for visibility_type, role_restriction in valid_configs:
            # Should not raise exception
            service._validate_role_configuration(visibility_type, role_restriction)

        # Test all valid non-role-based configurations
        valid_non_role_configs = [
            (VisibilityType.PRIVATE, None),
            (VisibilityType.PUBLIC, None),
            (VisibilityType.SPECIFIC_USERS, None),
        ]

        for visibility_type, role_restriction in valid_non_role_configs:
            # Should not raise exception
            service._validate_role_configuration(visibility_type, role_restriction)


class TestVisibilityServiceRoleValidationIntegration:
    """Integration tests for role validation with actual visibility operations"""

    def test_create_role_based_visibility_with_validation(self, db: Session):
        """Test creating role-based visibility with proper validation"""
        service = VisibilityService(db)

        # Create valid role-based visibility
        visibility = service.set_resource_visibility(
            resource_type=ResourceType.SERVER,
            resource_id=100,
            visibility_type=VisibilityType.ROLE_BASED,
            role_restriction=Role.operator,
            requesting_user_id=1,
        )

        assert visibility.visibility_type == VisibilityType.ROLE_BASED
        assert visibility.role_restriction == Role.operator
        assert visibility.resource_type == ResourceType.SERVER
        assert visibility.resource_id == 100

    def test_update_visibility_validates_role_changes(self, db: Session):
        """Test updating visibility validates role configuration changes"""
        service = VisibilityService(db)

        # Create initial visibility
        visibility = service.set_resource_visibility(
            resource_type=ResourceType.SERVER,
            resource_id=101,
            visibility_type=VisibilityType.PUBLIC,
            role_restriction=None,
        )
        assert visibility.visibility_type == VisibilityType.PUBLIC

        # Valid update: Change to role-based with role
        updated_visibility = service.set_resource_visibility(
            resource_type=ResourceType.SERVER,
            resource_id=101,
            visibility_type=VisibilityType.ROLE_BASED,
            role_restriction=Role.admin,
        )
        assert updated_visibility.visibility_type == VisibilityType.ROLE_BASED
        assert updated_visibility.role_restriction == Role.admin

        # Invalid update: Try to set role on non-role-based visibility
        with pytest.raises(
            ValueError, match="PRIVATE visibility cannot have role restrictions"
        ):
            service.set_resource_visibility(
                resource_type=ResourceType.SERVER,
                resource_id=101,
                visibility_type=VisibilityType.PRIVATE,
                role_restriction=Role.user,  # Invalid
            )

    def test_role_validation_error_messages_are_descriptive(self, db: Session):
        """Test that role validation error messages are clear and helpful"""
        service = VisibilityService(db)

        error_scenarios = [
            {
                "visibility_type": VisibilityType.PRIVATE,
                "role_restriction": Role.user,
                "expected_message": "PRIVATE visibility cannot have role restrictions",
            },
            {
                "visibility_type": VisibilityType.PUBLIC,
                "role_restriction": Role.operator,
                "expected_message": "PUBLIC visibility cannot have role restrictions",
            },
            {
                "visibility_type": VisibilityType.SPECIFIC_USERS,
                "role_restriction": Role.admin,
                "expected_message": "SPECIFIC_USERS visibility cannot have role restrictions",
            },
        ]

        for scenario in error_scenarios:
            with pytest.raises(ValueError, match=scenario["expected_message"]):
                service._validate_role_configuration(
                    scenario["visibility_type"], scenario["role_restriction"]
                )


if __name__ == "__main__":
    pytest.main([__file__])
