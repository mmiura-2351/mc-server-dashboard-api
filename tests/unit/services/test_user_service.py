import pytest
from fastapi import HTTPException
from app.users.schemas import UserCreate
from app.users.models import Role


class TestUserService:
    def test_register_first_user_as_admin(self, user_service):
        """最初のユーザーは管理者として登録される"""
        user_data = UserCreate(
            username="firstuser", email="first@example.com", password="password123"
        )

        user = user_service.register_user(user_data)

        assert user.username == "firstuser"
        assert user.email == "first@example.com"
        assert user.role == Role.admin
        assert user.is_approved is True
        assert user.is_active is True

    def test_register_second_user_as_regular_user(self, user_service, admin_user):
        """2番目以降のユーザーは一般ユーザーとして登録される"""
        user_data = UserCreate(
            username="seconduser", email="second@example.com", password="password123"
        )

        user = user_service.register_user(user_data)

        assert user.username == "seconduser"
        assert user.email == "second@example.com"
        assert user.role == Role.user
        assert user.is_approved is False
        assert user.is_active is True

    def test_register_duplicate_username(self, user_service, test_user):
        """重複するユーザー名での登録はエラー"""
        user_data = UserCreate(
            username="testuser",  # 既存のユーザー名
            email="different@example.com",
            password="password123",
        )

        with pytest.raises(HTTPException) as exc_info:
            user_service.register_user(user_data)

        assert exc_info.value.status_code == 400
        assert "Username already registered" in str(exc_info.value.detail)

    def test_authenticate_valid_user(self, user_service, test_user):
        """有効なユーザーの認証"""
        user = user_service.authenticate_user("testuser", "testpassword")

        assert user is not None
        assert user.username == "testuser"

    def test_authenticate_invalid_username(self, user_service):
        """存在しないユーザー名での認証"""
        user = user_service.authenticate_user("nonexistent", "password")

        assert user is None

    def test_authenticate_invalid_password(self, user_service, test_user):
        """間違ったパスワードでの認証"""
        user = user_service.authenticate_user("testuser", "wrongpassword")

        assert user is None

    def test_authenticate_unapproved_user(self, user_service, unapproved_user):
        """未承認ユーザーの認証はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            user_service.authenticate_user("unapproved", "unapprovedpassword")

        assert exc_info.value.status_code == 403
        assert "Account pending approval" in str(exc_info.value.detail)

    def test_approve_user_as_admin(self, user_service, admin_user, unapproved_user):
        """管理者によるユーザー承認"""
        approved_user = user_service.approve_user(admin_user, unapproved_user.id)

        assert approved_user.is_approved is True

    def test_approve_user_as_non_admin(self, user_service, test_user, unapproved_user):
        """一般ユーザーによるユーザー承認はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            user_service.approve_user(test_user, unapproved_user.id)

        assert exc_info.value.status_code == 403
        assert "Only admin can perform this action" in str(exc_info.value.detail)

    def test_approve_nonexistent_user(self, user_service, admin_user):
        """存在しないユーザーの承認はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            user_service.approve_user(admin_user, 999)

        assert exc_info.value.status_code == 404
        assert "User not found" in str(exc_info.value.detail)

    def test_update_role_as_admin(self, user_service, admin_user, test_user):
        """管理者によるロール変更"""
        updated_user = user_service.update_role(admin_user, test_user.id, "admin")

        assert updated_user.role.value == "admin"

    def test_update_role_as_non_admin(self, user_service, test_user):
        """一般ユーザーによるロール変更はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            user_service.update_role(test_user, test_user.id, "admin")

        assert exc_info.value.status_code == 403
        assert "Only admin can perform this action" in str(exc_info.value.detail)

    def test_update_role_nonexistent_user(self, user_service, admin_user):
        """存在しないユーザーのロール変更はエラー"""
        with pytest.raises(HTTPException) as exc_info:
            user_service.update_role(admin_user, 999, "admin")

        assert exc_info.value.status_code == 404
        assert "User not found" in str(exc_info.value.detail)
