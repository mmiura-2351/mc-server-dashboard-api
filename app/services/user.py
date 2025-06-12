from typing import Optional

from fastapi import HTTPException, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.auth.auth import create_access_token
from app.users import models, schemas

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def _get_user_by_username(self, username: str) -> Optional[models.User]:
        """Retrieve user by username"""
        return self.db.query(models.User).filter(models.User.username == username).first()

    def _get_user_by_id(self, user_id: int) -> Optional[models.User]:
        """Retrieve user by ID"""
        return self.db.query(models.User).filter(models.User.id == user_id).first()

    def get_user_by_id(self, user_id: int) -> Optional[models.User]:
        """Retrieve user by ID (public method)"""
        return self._get_user_by_id(user_id)

    def _check_admin_permission(self, current_user: models.User) -> None:
        """Check administrator permissions"""
        if current_user.role != models.Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can perform this action",
            )

    def _is_first_user(self) -> bool:
        """Check if this is the first user registration"""
        return self.db.query(models.User).count() == 0

    def register_user(self, user_create: schemas.UserCreate) -> models.User:
        """Register new user"""
        existing_user = self._get_user_by_username(user_create.username)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already registered",
            )

        # First user is automatically approved as administrator
        is_first_user = self._is_first_user()
        role = models.Role.admin if is_first_user else models.Role.user
        is_approved = is_first_user

        hashed_password = pwd_context.hash(user_create.password)
        db_user = models.User(
            username=user_create.username,
            email=user_create.email,
            hashed_password=hashed_password,
            role=role,
            is_approved=is_approved,
        )

        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        return db_user

    def authenticate_user(self, username: str, password: str) -> Optional[models.User]:
        """Authenticate user"""
        user = self._get_user_by_username(username)
        if not user:
            return None

        if not pwd_context.verify(password, user.hashed_password):
            return None

        if not user.is_approved:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account pending approval. Please wait for an administrator to approve your account.",
            )

        return user

    def update_role(
        self, current_user: models.User, target_user_id: int, new_role: models.Role
    ) -> models.User:
        """Update user role"""
        self._check_admin_permission(current_user)

        target_user = self._get_user_by_id(target_user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Set Role enum directly
        target_user.role = new_role

        self.db.commit()
        self.db.refresh(target_user)
        return target_user

    def approve_user(self, current_user: models.User, target_user_id: int) -> models.User:
        """Approve user"""
        self._check_admin_permission(current_user)

        target_user = self._get_user_by_id(target_user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        target_user.is_approved = True
        self.db.commit()
        self.db.refresh(target_user)
        return target_user

    def update_user_info(
        self, current_user: models.User, user_update: schemas.UserUpdate
    ) -> schemas.UserWithToken:
        """Update user information"""
        username_changed = False

        # Check for username duplication
        if user_update.username and user_update.username != current_user.username:
            existing_user = self._get_user_by_username(user_update.username)
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already exists",
                )
            current_user.username = user_update.username
            username_changed = True

        # Update email address
        if user_update.email and user_update.email != current_user.email:
            # Check for email address duplication
            existing_user = (
                self.db.query(models.User)
                .filter(
                    models.User.email == user_update.email,
                    models.User.id != current_user.id,
                )
                .first()
            )
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists",
                )
            current_user.email = user_update.email

        self.db.commit()
        self.db.refresh(current_user)

        # Generate new token if username was changed
        if username_changed:
            access_token = create_access_token(data={"sub": current_user.username})
            return schemas.UserWithToken(user=current_user, access_token=access_token)
        else:
            # Return empty token if username was not changed (frontend will handle this)
            return schemas.UserWithToken(user=current_user, access_token="")

    def update_password(
        self, current_user: models.User, password_update: schemas.PasswordUpdate
    ) -> schemas.UserWithToken:
        """Update password"""
        # Verify current password
        if not pwd_context.verify(
            password_update.current_password, current_user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        # Hash and save new password
        current_user.hashed_password = pwd_context.hash(password_update.new_password)
        self.db.commit()
        self.db.refresh(current_user)

        # Generate new token when password is changed
        access_token = create_access_token(data={"sub": current_user.username})
        return schemas.UserWithToken(user=current_user, access_token=access_token)

    def delete_user_account(
        self, current_user: models.User, user_delete: schemas.UserDelete
    ) -> None:
        """Delete user account"""
        # Verify password
        if not pwd_context.verify(user_delete.password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Password is incorrect"
            )

        # Reject deletion if this is the last administrator
        if current_user.role == models.Role.admin:
            admin_count = (
                self.db.query(models.User)
                .filter(models.User.role == models.Role.admin)
                .count()
            )
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete the last admin user",
                )

        self.db.delete(current_user)
        self.db.commit()

    def delete_user_by_admin(
        self, current_user: models.User, target_user_id: int
    ) -> None:
        """Delete user by administrator"""
        self._check_admin_permission(current_user)

        target_user = self._get_user_by_id(target_user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # If trying to delete own account
        if target_user.id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your own account",
            )

        # Reject deletion if this is the last administrator
        if target_user.role == models.Role.admin:
            admin_count = (
                self.db.query(models.User)
                .filter(models.User.role == models.Role.admin)
                .count()
            )
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete the last admin user",
                )

        self.db.delete(target_user)
        self.db.commit()

    def get_all_users(self, current_user: models.User) -> list[models.User]:
        """Get all users list (admin only)"""
        self._check_admin_permission(current_user)
        return self.db.query(models.User).all()
