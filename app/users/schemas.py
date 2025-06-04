from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str


class UserInDB(UserBase):
    hashed_password: str


class Role(str, Enum):
    admin = "admin"
    operator = "operator"
    user = "user"


class User(UserBase):
    id: int
    is_active: bool
    is_approved: bool
    role: Role

    model_config = ConfigDict(from_attributes=True)


class RoleUpdate(BaseModel):
    role: Role


class UserUpdate(BaseModel):
    username: str | None = None
    email: EmailStr | None = None


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str


class UserDelete(BaseModel):
    password: str


class UserWithToken(BaseModel):
    user: User
    access_token: str
    token_type: str = "bearer"
