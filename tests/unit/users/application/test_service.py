import pytest
from fastapi import HTTPException

from app.users.domain.value_objects import Role


class TestUserService:
    @pytest.mark.asyncio
    async def test_register_first_user_as_admin(self, user_service):
        """The first user is registered as admin."""
        user = await user_service.register_user(
            username="firstuser",
            email="first@example.com",
            plain_password="password123",
        )

        assert user.username == "firstuser"
        assert user.email == "first@example.com"
        assert user.role == Role.admin
        assert user.is_approved is True
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_register_second_user_as_regular_user(self, user_service, admin_user):
        """The second and later users are registered as regular users."""
        user = await user_service.register_user(
            username="seconduser",
            email="second@example.com",
            plain_password="password123",
        )

        assert user.username == "seconduser"
        assert user.email == "second@example.com"
        assert user.role == Role.user
        assert user.is_approved is False
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, user_service, test_user):
        """Registering with a duplicate username errors."""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.register_user(
                username="testuser",
                email="different@example.com",
                plain_password="password123",
            )

        assert exc_info.value.status_code == 400
        assert "Username already registered" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_authenticate_valid_user(self, user_service, test_user):
        """A valid user authenticates."""
        user = await user_service.authenticate_user("testuser", "testpassword")

        assert user is not None
        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_authenticate_invalid_username(self, user_service):
        """Authentication with an unknown username fails."""
        user = await user_service.authenticate_user("nonexistent", "password")

        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_invalid_password(self, user_service, test_user):
        """Authentication with a wrong password fails."""
        user = await user_service.authenticate_user("testuser", "wrongpassword")

        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_unapproved_user(self, user_service, unapproved_user):
        """Authentication for an unapproved user errors."""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.authenticate_user("unapproved", "unapprovedpassword")

        assert exc_info.value.status_code == 403
        assert "Account pending approval" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_approve_user_as_admin(self, user_service, admin_user, unapproved_user):
        """An admin can approve a user."""
        approved_user = await user_service.approve_user(admin_user, unapproved_user.id)

        assert approved_user.is_approved is True

    @pytest.mark.asyncio
    async def test_approve_user_as_non_admin(
        self, user_service, test_user, unapproved_user
    ):
        """A regular user cannot approve another user."""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.approve_user(test_user, unapproved_user.id)

        assert exc_info.value.status_code == 403
        assert "Only admin can perform this action" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_approve_nonexistent_user(self, user_service, admin_user):
        """Approving a non-existent user errors."""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.approve_user(admin_user, 999)

        assert exc_info.value.status_code == 404
        assert "User not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_update_role_as_admin(self, user_service, admin_user, test_user):
        """An admin can change a user role."""
        updated_user = await user_service.update_role(
            admin_user, test_user.id, Role.admin
        )

        assert updated_user.role == Role.admin

    @pytest.mark.asyncio
    async def test_update_role_as_non_admin(self, user_service, test_user):
        """A regular user cannot change roles."""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.update_role(test_user, test_user.id, Role.admin)

        assert exc_info.value.status_code == 403
        assert "Only admin can perform this action" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_update_role_nonexistent_user(self, user_service, admin_user):
        """Changing the role of a non-existent user errors."""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.update_role(admin_user, 999, Role.admin)

        assert exc_info.value.status_code == 404
        assert "User not found" in str(exc_info.value.detail)
