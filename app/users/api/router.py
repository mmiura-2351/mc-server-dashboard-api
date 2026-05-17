"""FastAPI router for the users domain.

All endpoints depend on `UserService` via DI — they never see SQLAlchemy
or the underlying repository directly.

Note: the route handlers accept `current_user` as the ORM `User` type
because `app.auth.dependencies.get_current_user` still returns the ORM
model (its migration to `UserEntity` is deferred — see PR description's
"Known pilot deviations" section). The handlers wrap the ORM user into
a `UserEntity` at the call site so the application service stays
entity-only.
"""

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.users import schemas
from app.users.api.dependencies import get_user_service
from app.users.application.results import UserWithToken
from app.users.application.service import UserService
from app.users.domain.entities import UserEntity
from app.users.models import User

router = APIRouter()


def _to_entity(user: User) -> UserEntity:
    """Adapt an ORM `User` to the pure `UserEntity` the service expects."""
    return UserEntity(
        id=user.id,
        username=user.username,
        email=user.email,
        hashed_password=user.hashed_password,
        role=user.role,
        is_active=user.is_active,
        is_approved=user.is_approved,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _to_schema(entity: UserEntity) -> schemas.User:
    """Adapt a `UserEntity` to the Pydantic response schema."""
    return schemas.User.model_validate(
        {
            "id": entity.id,
            "username": entity.username,
            "email": entity.email,
            "role": entity.role,
            "is_active": entity.is_active,
            "is_approved": entity.is_approved,
        }
    )


def _to_user_with_token_schema(result: UserWithToken) -> schemas.UserWithToken:
    return schemas.UserWithToken(
        user=_to_schema(result.user),
        access_token=result.access_token,
    )


@router.post("/register", response_model=schemas.User)
async def register(
    user_create: schemas.UserCreate,
    service: UserService = Depends(get_user_service),
):
    created = await service.register_user(
        username=user_create.username,
        email=user_create.email,
        plain_password=user_create.password,
    )
    return _to_schema(created)


@router.post("/approve/{user_id}", response_model=schemas.User)
async def approve_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    approved = await service.approve_user(_to_entity(current_user), user_id)
    return _to_schema(approved)


@router.put("/role/{user_id}", response_model=schemas.User)
async def change_role(
    user_id: int,
    role_update: schemas.RoleUpdate,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    updated = await service.update_role(
        _to_entity(current_user), user_id, role_update.role
    )
    return _to_schema(updated)


@router.get("/me", response_model=schemas.User)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=schemas.UserWithToken)
async def update_user_info(
    user_update: schemas.UserUpdate,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.update_user_info(
        _to_entity(current_user),
        new_username=user_update.username,
        new_email=user_update.email,
    )
    return _to_user_with_token_schema(result)


@router.put("/me/password", response_model=schemas.UserWithToken)
async def update_password(
    password_update: schemas.PasswordUpdate,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.update_password(
        _to_entity(current_user),
        current_plain_password=password_update.current_password,
        new_plain_password=password_update.new_password,
    )
    return _to_user_with_token_schema(result)


@router.delete("/me")
async def delete_user_account(
    user_delete: schemas.UserDelete,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    await service.delete_user_account(_to_entity(current_user), user_delete.password)
    return {"message": "Account deleted successfully"}


@router.get("/", response_model=list[schemas.User])
async def get_all_users(
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    users = await service.get_all_users(_to_entity(current_user))
    return [_to_schema(u) for u in users]


@router.delete("/{user_id}")
async def delete_user_by_admin(
    user_id: int,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    await service.delete_user_by_admin(_to_entity(current_user), user_id)
    return {"message": "User deleted successfully"}
