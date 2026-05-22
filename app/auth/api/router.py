"""FastAPI router for the auth domain.

All endpoints depend on `AuthService` and `UserService` via DI — they
never see SQLAlchemy directly.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.audit.service import AuditService
from app.auth.api.dependencies import get_auth_service
from app.auth.application.service import AuthService
from app.auth.auth import create_access_token
from app.types import DatabaseSession
from app.users.api.dependencies import get_user_service
from app.users.application.service import UserService

router = APIRouter()


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DatabaseSession,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    auth_service: AuthService = Depends(get_auth_service),
):
    user_entity = None
    try:
        user_entity = await user_service.authenticate_user(
            form_data.username, form_data.password
        )
        if user_entity is None:
            AuditService.log_authentication_event(
                request=request,
                action="login",
                details={
                    "username": form_data.username,
                    "reason": "invalid_credentials",
                },
                success=False,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
            )

        access_token = create_access_token(data={"sub": user_entity.username})
        refresh_token = await auth_service.create_refresh_token(user_entity.id)

        AuditService.log_authentication_event(
            request=request,
            action="login",
            user_id=user_entity.id,
            details={
                "username": user_entity.username,
                "user_role": user_entity.role.value,
            },
            success=True,
        )

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
    except HTTPException as e:
        if user_entity is None:
            AuditService.log_authentication_event(
                request=request,
                action="login",
                details={
                    "username": form_data.username,
                    "reason": "authentication_error",
                    "error": str(e.detail),
                },
                success=False,
            )
        raise


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    token_request: RefreshTokenRequest,
    db: DatabaseSession,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    auth_service: AuthService = Depends(get_auth_service),
):
    user_id = await auth_service.verify_refresh_token(token_request.refresh_token)
    if not user_id:
        AuditService.log_authentication_event(
            request=request,
            action="token_refresh",
            details={"reason": "invalid_refresh_token"},
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = await user_service.get_user_by_id(user_id)
    if user is None or not user.is_active:
        AuditService.log_authentication_event(
            request=request,
            action="token_refresh",
            user_id=user_id,
            details={"reason": "user_inactive_or_not_found"},
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    access_token = create_access_token(data={"sub": user.username})
    new_refresh_token = await auth_service.create_refresh_token(user.id)

    AuditService.log_authentication_event(
        request=request,
        action="token_refresh",
        user_id=user.id,
        details={"username": user.username},
        success=True,
    )

    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout")
async def logout(
    token_request: RefreshTokenRequest,
    db: DatabaseSession,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
):
    user_id = await auth_service.verify_refresh_token(token_request.refresh_token)
    success = await auth_service.revoke_refresh_token(token_request.refresh_token)
    if not success:
        AuditService.log_authentication_event(
            request=request,
            action="logout",
            user_id=user_id,
            details={"reason": "invalid_refresh_token"},
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid refresh token"
        )

    AuditService.log_authentication_event(
        request=request,
        action="logout",
        user_id=user_id,
        details={"logout_method": "refresh_token_revocation"},
        success=True,
    )

    return {"message": "Successfully logged out"}
