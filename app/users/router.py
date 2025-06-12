from fastapi import APIRouter

from app.services.user import UserService
from app.types import CurrentUser, DatabaseSession
from app.users import schemas

router = APIRouter()


@router.post("/register", response_model=schemas.User)
def register(user_create: schemas.UserCreate, db: DatabaseSession):
    service = UserService(db)
    return service.register_user(user_create)


@router.post("/approve/{user_id}", response_model=schemas.User)
def approve_user(user_id: int, current_user: CurrentUser, db: DatabaseSession):
    service = UserService(db)
    return service.approve_user(current_user, user_id)


@router.put("/role/{user_id}", response_model=schemas.User)
def change_role(
    user_id: int,
    role_update: schemas.RoleUpdate,
    current_user: CurrentUser,
    db: DatabaseSession,
):
    service = UserService(db)
    return service.update_role(current_user, user_id, role_update.role)


@router.get("/me", response_model=schemas.User)
def get_current_user_info(current_user: CurrentUser):
    return current_user


@router.put("/me", response_model=schemas.UserWithToken)
def update_user_info(
    user_update: schemas.UserUpdate, current_user: CurrentUser, db: DatabaseSession
):
    service = UserService(db)
    return service.update_user_info(current_user, user_update)


@router.put("/me/password", response_model=schemas.UserWithToken)
def update_password(
    password_update: schemas.PasswordUpdate,
    current_user: CurrentUser,
    db: DatabaseSession,
):
    service = UserService(db)
    return service.update_password(current_user, password_update)


@router.delete("/me")
def delete_user_account(
    user_delete: schemas.UserDelete, current_user: CurrentUser, db: DatabaseSession
):
    service = UserService(db)
    service.delete_user_account(current_user, user_delete)
    return {"message": "Account deleted successfully"}


@router.get("/", response_model=list[schemas.User])
def get_all_users(current_user: CurrentUser, db: DatabaseSession):
    service = UserService(db)
    return service.get_all_users(current_user)


@router.delete("/{user_id}")
def delete_user_by_admin(user_id: int, current_user: CurrentUser, db: DatabaseSession):
    service = UserService(db)
    service.delete_user_by_admin(current_user, user_id)
    return {"message": "User deleted successfully"}
