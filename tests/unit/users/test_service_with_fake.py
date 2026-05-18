"""Service-level unit tests using FakeUsersUnitOfWork + FakeUserRepository.

Demonstrates the target pattern for testing application-layer services
in the users domain.
"""

import pytest
from fastapi import HTTPException

from app.users.application.service import UserService, pwd_context
from app.users.domain.entities import UserEntity
from app.users.models import Role
from tests.unit.users.fakes import FakeUsersUnitOfWork


@pytest.fixture
def uow() -> FakeUsersUnitOfWork:
    return FakeUsersUnitOfWork()


@pytest.fixture
def service(uow: FakeUsersUnitOfWork) -> UserService:
    return UserService(uow=uow)


@pytest.fixture
def admin_entity() -> UserEntity:
    return UserEntity(
        id=1,
        username="admin",
        email="admin@example.com",
        hashed_password="x",
        role=Role.admin,
        is_active=True,
        is_approved=True,
    )


@pytest.fixture
def regular_entity() -> UserEntity:
    return UserEntity(
        id=2,
        username="bob",
        email="bob@example.com",
        hashed_password=pwd_context.hash("supersecret"),
        role=Role.user,
        is_active=True,
        is_approved=True,
    )


class TestRegisterUser:
    @pytest.mark.asyncio
    async def test_first_user_becomes_admin(self, service: UserService) -> None:
        user = await service.register_user("alice", "alice@x.com", "pw1234")
        assert user.role == Role.admin
        assert user.is_approved is True

    @pytest.mark.asyncio
    async def test_second_user_is_pending(self, service: UserService) -> None:
        await service.register_user("alice", "alice@x.com", "pw1234")
        user = await service.register_user("bob", "bob@x.com", "pw1234")
        assert user.role == Role.user
        assert user.is_approved is False

    @pytest.mark.asyncio
    async def test_duplicate_username_rejected(self, service: UserService) -> None:
        await service.register_user("alice", "alice@x.com", "pw1234")
        with pytest.raises(HTTPException) as exc:
            await service.register_user("alice", "alice2@x.com", "pw1234")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_duplicate_email_rejected(self, service: UserService) -> None:
        await service.register_user("alice", "shared@x.com", "pw1234")
        with pytest.raises(HTTPException) as exc:
            await service.register_user("bob", "shared@x.com", "pw1234")
        assert exc.value.status_code == 400
        assert "email" in exc.value.detail.lower()


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_valid_credentials(self, service: UserService) -> None:
        await service.register_user("alice", "alice@x.com", "pw1234")
        user = await service.authenticate_user("alice", "pw1234")
        assert user is not None
        assert user.username == "alice"

    @pytest.mark.asyncio
    async def test_wrong_password(self, service: UserService) -> None:
        await service.register_user("alice", "alice@x.com", "pw1234")
        assert await service.authenticate_user("alice", "wrong") is None

    @pytest.mark.asyncio
    async def test_missing_user(self, service: UserService) -> None:
        assert await service.authenticate_user("nobody", "pw") is None

    @pytest.mark.asyncio
    async def test_unapproved_user_raises_403(
        self, service: UserService, uow: FakeUsersUnitOfWork
    ) -> None:
        # First user is auto-approved, so create two: the second is unapproved.
        await service.register_user("admin", "admin@x.com", "pw")
        await service.register_user("alice", "alice@x.com", "pw1234")
        with pytest.raises(HTTPException) as exc:
            await service.authenticate_user("alice", "pw1234")
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_inactive_user_returns_none(
        self, service: UserService, uow: FakeUsersUnitOfWork
    ) -> None:
        from app.users.domain.entities import UpdateUserCommand

        await service.register_user("admin", "admin@x.com", "pw1234")
        admin = await uow.users.get_by_username("admin")
        assert admin is not None and admin.id is not None
        # Deactivating an otherwise-valid, approved account must block login.
        await uow.users.update(admin.id, UpdateUserCommand(is_active=False))
        assert await service.authenticate_user("admin", "pw1234") is None


class TestAdminActions:
    @pytest.mark.asyncio
    async def test_approve_user_admin_only(
        self, service: UserService, uow: FakeUsersUnitOfWork, regular_entity
    ) -> None:
        with pytest.raises(HTTPException) as exc:
            await service.approve_user(regular_entity, target_user_id=99)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_admin_succeeds_when_another_admin_exists(
        self, service: UserService, uow: FakeUsersUnitOfWork
    ) -> None:
        """Symmetric counter-case to `test_delete_last_admin_blocked`.

        With two admins, deleting one should succeed (the last-admin
        guard only kicks in when there is exactly one).
        """
        from app.users.domain.entities import CreateUserCommand

        password = "supersecret"
        hashed = pwd_context.hash(password)
        for username in ("admin-a", "admin-b"):
            await uow.users.create(
                CreateUserCommand(
                    username=username,
                    email=f"{username}@x.com",
                    hashed_password=hashed,
                    role=Role.admin,
                    is_approved=True,
                )
            )
        admin_a = await uow.users.get_by_username("admin-a")
        assert admin_a is not None

        await service.delete_user_account(admin_a, plain_password=password)

        assert await uow.users.get_by_username("admin-a") is None
        assert await uow.users.count_by_role(Role.admin) == 1

    @pytest.mark.asyncio
    async def test_delete_last_admin_blocked(
        self, service: UserService, uow: FakeUsersUnitOfWork
    ) -> None:
        # Seed an admin whose password we know so we can pass the
        # password-verify step and hit the "last admin" check.
        password = "supersecret"
        from app.users.domain.entities import CreateUserCommand

        await uow.users.create(
            CreateUserCommand(
                username="solo-admin",
                email="solo@x.com",
                hashed_password=pwd_context.hash(password),
                role=Role.admin,
                is_approved=True,
            )
        )
        admin = await uow.users.get_by_username("solo-admin")
        assert admin is not None

        with pytest.raises(HTTPException) as exc:
            await service.delete_user_account(admin, plain_password=password)
        assert exc.value.status_code == 400
        assert "last admin" in exc.value.detail.lower()
