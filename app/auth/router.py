from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel

from app.audit.service import AuditService
from app.auth.auth import (
    create_access_token,
    create_refresh_token,
    revoke_refresh_token,
    verify_refresh_token,
)
from app.services.user import UserService
from app.types import DatabaseSession

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DatabaseSession,
    request: Request,
):
    service = UserService(db)
    user = None
    try:
        user = service.authenticate_user(form_data.username, form_data.password)
        if not user:
            # Log failed authentication
            AuditService.log_authentication_event(
                db=db,
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

        access_token = create_access_token(data={"sub": user.username})
        refresh_token = create_refresh_token(user.id, db)

        # Log successful authentication
        AuditService.log_authentication_event(
            db=db,
            request=request,
            action="login",
            user_id=user.id,
            details={
                "username": user.username,
                "user_role": user.role.value,
            },
            success=True,
        )

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
    except HTTPException as e:
        # Log authentication failure if not already logged
        if not user:
            AuditService.log_authentication_event(
                db=db,
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
def refresh_access_token(
    token_request: RefreshTokenRequest, db: DatabaseSession, request: Request
):
    user_id = verify_refresh_token(token_request.refresh_token, db)
    if not user_id:
        # Log failed token refresh
        AuditService.log_authentication_event(
            db=db,
            request=request,
            action="token_refresh",
            details={"reason": "invalid_refresh_token"},
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    service = UserService(db)
    user = service.get_user_by_id(user_id)
    if not user or not user.is_active:
        # Log failed token refresh
        AuditService.log_authentication_event(
            db=db,
            request=request,
            action="token_refresh",
            user_id=user_id,
            details={"reason": "user_inactive_or_not_found"},
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )

    # Generate new access token and refresh token
    access_token = create_access_token(data={"sub": user.username})
    new_refresh_token = create_refresh_token(user.id, db)

    # Log successful token refresh
    AuditService.log_authentication_event(
        db=db,
        request=request,
        action="token_refresh",
        user_id=user.id,
        details={"username": user.username},
        success=True,
    )

    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout")
def logout(token_request: RefreshTokenRequest, db: DatabaseSession, request: Request):
    # Extract user ID from refresh token before revoking
    user_id = verify_refresh_token(token_request.refresh_token, db)

    success = revoke_refresh_token(token_request.refresh_token, db)
    if not success:
        # Log failed logout
        AuditService.log_authentication_event(
            db=db,
            request=request,
            action="logout",
            user_id=user_id,
            details={"reason": "invalid_refresh_token"},
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid refresh token"
        )

    # Log successful logout
    AuditService.log_authentication_event(
        db=db,
        request=request,
        action="logout",
        user_id=user_id,
        details={"logout_method": "refresh_token_revocation"},
        success=True,
    )

    return {"message": "Successfully logged out"}
