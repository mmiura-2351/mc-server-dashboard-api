"""User Service (application layer).

Orchestrates user-management use cases through the `UsersUnitOfWork`
Port. Depends only on `domain/`. Must not import from `adapters/` or
`api/`.

Result DTOs that cross the application/api boundary live in
`application.results`.
"""

from typing import List

from fastapi import HTTPException, status
from passlib.context import CryptContext

from app.auth.auth import create_access_token
from app.users.application.results import UserWithToken
from app.users.domain.entities import (
    CreateUserCommand,
    UpdateUserCommand,
    UserEntity,
)
from app.users.domain.ports import UsersUnitOfWork
from app.users.models import Role

# The password hasher is a pure CPU operation with no I/O — its presence
# in the application layer does not violate the framework-isolation rule.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserService:
    """User-management use cases."""

    def __init__(self, uow: UsersUnitOfWork):
        self._uow: UsersUnitOfWork = uow

    # ----- Queries -----

    async def get_user_by_id(self, user_id: int) -> UserEntity | None:
        async with self._uow as uow:
            return await uow.users.get_by_id(user_id)

    async def get_all_users(self, current_user: UserEntity) -> List[UserEntity]:
        self._require_admin(current_user)
        async with self._uow as uow:
            return await uow.users.list_all()

    # ----- Registration & authentication -----

    async def register_user(
        self,
        username: str,
        email: str,
        plain_password: str,
    ) -> UserEntity:
        """Register a new user.

        The first registered user is automatically promoted to `admin`
        and pre-approved, matching the legacy behaviour.
        """
        async with self._uow as uow:
            existing = await uow.users.get_by_username(username)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already registered",
                )

            is_first_user = await uow.users.count() == 0
            role = Role.admin if is_first_user else Role.user
            is_approved = is_first_user

            hashed = pwd_context.hash(plain_password)
            created = await uow.users.create(
                CreateUserCommand(
                    username=username,
                    email=email,
                    hashed_password=hashed,
                    role=role,
                    is_approved=is_approved,
                )
            )
            await uow.commit()
            return created

    async def authenticate_user(
        self, username: str, plain_password: str
    ) -> UserEntity | None:
        """Validate credentials and return the user, or `None` if invalid.

        Raises `HTTPException(403)` if the user exists but is not yet
        approved — matches the legacy contract so router-level handlers
        stay unchanged.
        """
        async with self._uow as uow:
            user = await uow.users.get_by_username(username)
        if user is None or not pwd_context.verify(plain_password, user.hashed_password):
            return None
        if not user.is_approved:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Account pending approval. Please wait for an "
                    "administrator to approve your account."
                ),
            )
        return user

    # ----- Admin actions -----

    async def approve_user(
        self, current_user: UserEntity, target_user_id: int
    ) -> UserEntity:
        self._require_admin(current_user)
        async with self._uow as uow:
            target = await uow.users.get_by_id(target_user_id)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )
            updated = await uow.users.update(
                target_user_id, UpdateUserCommand(is_approved=True)
            )
            await uow.commit()
            assert updated is not None
            return updated

    async def update_role(
        self,
        current_user: UserEntity,
        target_user_id: int,
        new_role: Role,
    ) -> UserEntity:
        self._require_admin(current_user)
        async with self._uow as uow:
            target = await uow.users.get_by_id(target_user_id)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )
            updated = await uow.users.update(
                target_user_id, UpdateUserCommand(role=new_role)
            )
            await uow.commit()
            assert updated is not None
            return updated

    async def delete_user_by_admin(
        self, current_user: UserEntity, target_user_id: int
    ) -> None:
        self._require_admin(current_user)
        async with self._uow as uow:
            target = await uow.users.get_by_id(target_user_id)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )
            if target.id == current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete your own account",
                )
            if target.role == Role.admin:
                admin_count = await uow.users.count_by_role(Role.admin)
                if admin_count <= 1:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot delete the last admin user",
                    )
            await uow.users.delete(target_user_id)
            await uow.commit()

    # ----- Self-service -----

    async def update_user_info(
        self,
        current_user: UserEntity,
        new_username: str | None,
        new_email: str | None,
    ) -> UserWithToken:
        username_changed = False
        async with self._uow as uow:
            command_kwargs: dict = {}
            if new_username and new_username != current_user.username:
                existing = await uow.users.get_by_username(new_username)
                if existing is not None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Username already exists",
                    )
                command_kwargs["username"] = new_username
                username_changed = True

            if new_email and new_email != current_user.email:
                if await uow.users.email_exists_for_other_user(
                    new_email,
                    current_user.id,
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email already exists",
                    )
                command_kwargs["email"] = new_email

            updated = await uow.users.update(
                current_user.id,
                UpdateUserCommand(**command_kwargs),
            )
            await uow.commit()
            assert updated is not None

        access_token = (
            create_access_token(data={"sub": updated.username})
            if username_changed
            else ""
        )
        return UserWithToken(user=updated, access_token=access_token)

    async def update_password(
        self,
        current_user: UserEntity,
        current_plain_password: str,
        new_plain_password: str,
    ) -> UserWithToken:
        if not pwd_context.verify(current_plain_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        new_hash = pwd_context.hash(new_plain_password)
        async with self._uow as uow:
            updated = await uow.users.update(
                current_user.id,
                UpdateUserCommand(hashed_password=new_hash),
            )
            await uow.commit()
            assert updated is not None

        access_token = create_access_token(data={"sub": updated.username})
        return UserWithToken(user=updated, access_token=access_token)

    async def delete_user_account(
        self,
        current_user: UserEntity,
        plain_password: str,
    ) -> None:
        if not pwd_context.verify(plain_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Password is incorrect"
            )

        async with self._uow as uow:
            if current_user.role == Role.admin:
                admin_count = await uow.users.count_by_role(Role.admin)
                if admin_count <= 1:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot delete the last admin user",
                    )
            await uow.users.delete(current_user.id)
            await uow.commit()

    # ----- Internal helpers -----

    @staticmethod
    def _require_admin(current_user: UserEntity) -> None:
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can perform this action",
            )
