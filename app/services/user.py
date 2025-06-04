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
        """ユーザー名でユーザーを取得"""
        return self.db.query(models.User).filter(models.User.username == username).first()

    def _get_user_by_id(self, user_id: int) -> Optional[models.User]:
        """IDでユーザーを取得"""
        return self.db.query(models.User).filter(models.User.id == user_id).first()

    def _check_admin_permission(self, current_user: models.User) -> None:
        """管理者権限をチェック"""
        if current_user.role != models.Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can perform this action",
            )

    def _is_first_user(self) -> bool:
        """最初のユーザーかどうかをチェック"""
        return self.db.query(models.User).count() == 0

    def register_user(self, user_create: schemas.UserCreate) -> models.User:
        """新規ユーザー登録"""
        existing_user = self._get_user_by_username(user_create.username)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already registered",
            )

        # 最初のユーザーは管理者として自動承認
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
        """ユーザー認証"""
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
        """ユーザーのロールを更新"""
        self._check_admin_permission(current_user)

        target_user = self._get_user_by_id(target_user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Role enumを直接設定
        target_user.role = new_role

        self.db.commit()
        self.db.refresh(target_user)
        return target_user

    def approve_user(self, current_user: models.User, target_user_id: int) -> models.User:
        """ユーザーを承認"""
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
        """ユーザー情報を更新"""
        username_changed = False

        # ユーザー名の重複チェック
        if user_update.username and user_update.username != current_user.username:
            existing_user = self._get_user_by_username(user_update.username)
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already exists",
                )
            current_user.username = user_update.username
            username_changed = True

        # メールアドレスの更新
        if user_update.email and user_update.email != current_user.email:
            # メールアドレスの重複チェック
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

        # usernameが変更された場合は新しいトークンを生成
        if username_changed:
            access_token = create_access_token(data={"sub": current_user.username})
            return schemas.UserWithToken(user=current_user, access_token=access_token)
        else:
            # usernameが変更されていない場合は空のトークンを返す（フロントエンドで判定）
            return schemas.UserWithToken(user=current_user, access_token="")

    def update_password(
        self, current_user: models.User, password_update: schemas.PasswordUpdate
    ) -> schemas.UserWithToken:
        """パスワードを更新"""
        # 現在のパスワードを確認
        if not pwd_context.verify(
            password_update.current_password, current_user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        # 新しいパスワードをハッシュ化して保存
        current_user.hashed_password = pwd_context.hash(password_update.new_password)
        self.db.commit()
        self.db.refresh(current_user)

        # パスワード変更時は新しいトークンを生成
        access_token = create_access_token(data={"sub": current_user.username})
        return schemas.UserWithToken(user=current_user, access_token=access_token)

    def delete_user_account(
        self, current_user: models.User, user_delete: schemas.UserDelete
    ) -> None:
        """ユーザーアカウントを削除"""
        # パスワードを確認
        if not pwd_context.verify(user_delete.password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Password is incorrect"
            )

        # 管理者が最後の一人の場合は削除を拒否
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
        """管理者によるユーザー削除"""
        self._check_admin_permission(current_user)

        target_user = self._get_user_by_id(target_user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # 自分自身を削除しようとした場合
        if target_user.id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your own account",
            )

        # 管理者が最後の一人の場合は削除を拒否
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
        """全ユーザー一覧を取得（管理者のみ）"""
        self._check_admin_permission(current_user)
        return self.db.query(models.User).all()
