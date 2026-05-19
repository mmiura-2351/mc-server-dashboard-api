import pytest
from fastapi import HTTPException

from app.users.models import Role


class TestUserService:
    @pytest.mark.asyncio
    async def test_register_first_user_as_admin(self, user_service):
        """最初のユーザーは管理者として登録される"""
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
        """2番目以降のユーザーは一般ユーザーとして登録される"""
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
        """重複するユーザー名での登録はエラー"""
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
        """有効なユーザーの認証"""
        user = await user_service.authenticate_user("testuser", "testpassword")

        assert user is not None
        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_authenticate_invalid_username(self, user_service):
        """存在しないユーザー名での認証"""
        user = await user_service.authenticate_user("nonexistent", "password")

        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_invalid_password(self, user_service, test_user):
        """間違ったパスワードでの認証"""
        user = await user_service.authenticate_user("testuser", "wrongpassword")

        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_unapproved_user(self, user_service, unapproved_user):
        """未承認ユーザーの認証はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.authenticate_user("unapproved", "unapprovedpassword")

        assert exc_info.value.status_code == 403
        assert "Account pending approval" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_approve_user_as_admin(self, user_service, admin_user, unapproved_user):
        """管理者によるユーザー承認"""
        approved_user = await user_service.approve_user(admin_user, unapproved_user.id)

        assert approved_user.is_approved is True

    @pytest.mark.asyncio
    async def test_approve_user_as_non_admin(
        self, user_service, test_user, unapproved_user
    ):
        """一般ユーザーによるユーザー承認はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.approve_user(test_user, unapproved_user.id)

        assert exc_info.value.status_code == 403
        assert "Only admin can perform this action" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_approve_nonexistent_user(self, user_service, admin_user):
        """存在しないユーザーの承認はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.approve_user(admin_user, 999)

        assert exc_info.value.status_code == 404
        assert "User not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_update_role_as_admin(self, user_service, admin_user, test_user):
        """管理者によるロール変更"""
        updated_user = await user_service.update_role(
            admin_user, test_user.id, Role.admin
        )

        assert updated_user.role == Role.admin

    @pytest.mark.asyncio
    async def test_update_role_as_non_admin(self, user_service, test_user):
        """一般ユーザーによるロール変更はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.update_role(test_user, test_user.id, Role.admin)

        assert exc_info.value.status_code == 403
        assert "Only admin can perform this action" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_update_role_nonexistent_user(self, user_service, admin_user):
        """存在しないユーザーのロール変更はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            await user_service.update_role(admin_user, 999, Role.admin)

        assert exc_info.value.status_code == 404
        assert "User not found" in str(exc_info.value.detail)
