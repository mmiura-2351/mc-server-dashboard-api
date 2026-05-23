from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

from app.users.application.password_policy import get_password_policy
from app.users.domain.value_objects import PasswordPolicyError


def _validate_password(value: str) -> str:
    """Field-level password validator shared by `UserCreate` / `PasswordUpdate`.

    Performs the *value-only* portion of the policy check (length,
    complexity, common-password blocklist, simple-pattern screening).
    Cross-field checks (username / e-mail containment) run from the
    model-level validator after both fields are available.
    """
    policy = get_password_policy()
    # We intentionally skip the username/email check here — see
    # the model-level validator below — but still surface every other
    # violation up to Pydantic as a friendly message.
    try:
        # Build a temporary policy view that ignores user-info for now.
        policy_no_user_info = policy.__class__(
            min_length=policy.min_length,
            max_length=policy.max_length,
            require_complexity=policy.require_complexity,
            long_password_complexity_escape=policy.long_password_complexity_escape,
            check_common_passwords=policy.check_common_passwords,
            common_passwords=policy.common_passwords,
            forbid_user_info=False,
            forbid_simple_patterns=policy.forbid_simple_patterns,
        )
        policy_no_user_info.validate(value)
    except PasswordPolicyError as exc:
        # Pydantic surfaces this as a 422 with the joined reason.
        raise ValueError(str(exc)) from exc
    return value


class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str

    @field_validator("password")
    @classmethod
    def _check_password_policy(cls, v: str) -> str:
        return _validate_password(v)

    @model_validator(mode="after")
    def _check_password_user_info(self) -> "UserCreate":
        policy = get_password_policy()
        try:
            policy.validate(
                self.password,
                username=self.username,
                email=self.email,
            )
        except PasswordPolicyError as exc:
            raise ValueError(str(exc)) from exc
        return self


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

    @field_validator("new_password")
    @classmethod
    def _check_password_policy(cls, v: str) -> str:
        return _validate_password(v)


class UserDelete(BaseModel):
    password: str


class UserWithToken(BaseModel):
    user: User
    access_token: str
    token_type: str = "bearer"
