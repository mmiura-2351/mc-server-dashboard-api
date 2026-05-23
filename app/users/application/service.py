"""User Service (application layer).

Orchestrates user-management use cases through the `UsersUnitOfWork`
Port. Depends only on `domain/`. Must not import from `adapters/` or
`api/`.

Result DTOs that cross the application/api boundary live in
`application.results`.
"""

from datetime import datetime, timezone
from typing import List

from fastapi import HTTPException, status
from passlib.context import CryptContext

from app.auth.auth import create_access_token
from app.users.application.password_policy import get_password_policy
from app.users.application.results import UserWithToken
from app.users.domain.entities import (
    CreateUserCommand,
    UpdateUserCommand,
    UserEntity,
)
from app.users.domain.ports import UsersUnitOfWork
from app.users.domain.value_objects import PasswordPolicyError, Role

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
        # Defense-in-depth: the schema validator already enforced this
        # for HTTP callers, but direct service callers (and tests) get
        # the same guarantee here.
        self._enforce_password_policy(plain_password, username=username, email=email)
        async with self._uow as uow:
            existing = await uow.users.get_by_username(username)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already registered",
                )

            existing_email = await uow.users.get_by_email(email)
            if existing_email is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered",
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
                    password_set_at=datetime.now(timezone.utc),
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
        # Deactivated accounts cannot authenticate. Mirrors the refresh-token
        # path in `app/auth/api/router.py`, which treats `is_active=False` the
        # same as "no such user" — the router maps `None` to 401.
        if not user.is_active:
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

    async def deactivate_user(
        self, current_user: UserEntity, target_user_id: int
    ) -> UserEntity:
        """Admin-forced deactivation (Issue #237).

        Flips ``is_active`` to False and bumps ``token_version`` in a
        single UoW transaction. Returns the updated entity so the
        caller can invoke ``AuthService.revoke_all_refresh_tokens_for``
        outside this transaction. (Refresh-token revocation lives in
        the auth domain's own UoW; keeping the two concerns in
        separate transactions matches the existing layering and is
        acceptable because the access-token ``tv`` bump alone is
        already sufficient to block any *new* refresh exchange from
        minting a usable access token.)
        """
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
                    detail="Cannot deactivate your own account",
                )
            # Mirror the `delete_user_by_admin` last-admin guard so an
            # operator cannot accidentally lock out every admin by
            # deactivation (which would be just as catastrophic as
            # deletion).
            if target.role == Role.admin and target.is_active:
                admin_count = await uow.users.count_by_role(Role.admin)
                if admin_count <= 1:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot deactivate the last admin user",
                    )
            updated = await uow.users.update(
                target_user_id,
                UpdateUserCommand(
                    is_active=False,
                    token_version=(target.token_version or 0) + 1,
                ),
            )
            await uow.commit()
            assert updated is not None
            return updated

    async def reactivate_user(
        self, current_user: UserEntity, target_user_id: int
    ) -> UserEntity:
        """Admin-forced reactivation (Issue #237).

        Restores ``is_active=True`` without changing ``token_version``
        — a previously revoked access token whose `tv` was bumped on
        deactivation will still be rejected (which is the desired
        property; the user must log in afresh).
        """
        self._require_admin(current_user)
        async with self._uow as uow:
            target = await uow.users.get_by_id(target_user_id)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )
            updated = await uow.users.update(
                target_user_id, UpdateUserCommand(is_active=True)
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
            create_access_token(
                data={"sub": updated.username, "tv": updated.token_version}
            )
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

        # Defense-in-depth password-policy check (mirrors the schema
        # validator). Raises HTTP 400 if the new password is weak.
        self._enforce_password_policy(
            new_plain_password,
            username=current_user.username,
            email=current_user.email,
        )

        new_hash = pwd_context.hash(new_plain_password)
        # Issue #237: bumping `token_version` here invalidates every
        # previously issued access token (and indirectly every refresh
        # exchange that would have minted one with the old `tv`).
        # The new token returned below carries the bumped value so the
        # caller's UI session continues uninterrupted.
        next_tv = (current_user.token_version or 0) + 1
        async with self._uow as uow:
            updated = await uow.users.update(
                current_user.id,
                UpdateUserCommand(
                    hashed_password=new_hash,
                    password_set_at=datetime.now(timezone.utc),
                    token_version=next_tv,
                ),
            )
            await uow.commit()
            assert updated is not None

        access_token = create_access_token(
            data={"sub": updated.username, "tv": updated.token_version}
        )
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

    @staticmethod
    def _enforce_password_policy(
        plain_password: str,
        *,
        username: str,
        email: str,
    ) -> None:
        """Translate a `PasswordPolicyError` into HTTP 400.

        Direct service callers (and tests) get the same protection as
        HTTP callers whose Pydantic schema validator would 422 them.
        """
        try:
            get_password_policy().validate(plain_password, username=username, email=email)
        except PasswordPolicyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Password does not meet policy: {exc}",
            ) from exc
