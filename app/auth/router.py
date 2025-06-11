from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel

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
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: DatabaseSession
):
    service = UserService(db)
    try:
        user = service.authenticate_user(form_data.username, form_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
            )
        access_token = create_access_token(data={"sub": user.username})
        refresh_token = create_refresh_token(user.id, db)

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
    except HTTPException:
        # Re-raise HTTPException thrown by UserService.authenticate_user
        raise


@router.post("/refresh", response_model=TokenResponse)
def refresh_access_token(request: RefreshTokenRequest, db: DatabaseSession):
    user_id = verify_refresh_token(request.refresh_token, db)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    service = UserService(db)
    user = service.get_user_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )

    # Generate new access token and refresh token
    access_token = create_access_token(data={"sub": user.username})
    new_refresh_token = create_refresh_token(user.id, db)

    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout")
def logout(request: RefreshTokenRequest, db: DatabaseSession):
    success = revoke_refresh_token(request.refresh_token, db)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid refresh token"
        )

    return {"message": "Successfully logged out"}
