from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext

from app.auth.auth import create_access_token
from app.services.user import UserService
from app.types import DatabaseSession

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.post("/token")
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
        return {"access_token": access_token, "token_type": "bearer"}
    except HTTPException:
        # UserService.authenticate_userで投げられたHTTPExceptionをそのまま再発生
        raise
