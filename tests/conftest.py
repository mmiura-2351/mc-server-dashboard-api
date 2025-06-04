import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.core.database import get_db, Base
from app.users.models import User, Role
from app.services.user import UserService
from passlib.context import CryptContext

# テスト用のインメモリSQLiteデータベース
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    # dbフィクスチャを依存関係に追加してテーブルが作成されるようにする
    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_user(db):
    """テスト用ユーザーを作成"""
    hashed_password = pwd_context.hash("testpassword")
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=hashed_password,
        role=Role.user,
        is_approved=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user(db):
    """テスト用管理者ユーザーを作成"""
    hashed_password = pwd_context.hash("adminpassword")
    user = User(
        username="admin",
        email="admin@example.com",
        hashed_password=hashed_password,
        role=Role.admin,
        is_approved=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def unapproved_user(db):
    """未承認のテスト用ユーザーを作成"""
    hashed_password = pwd_context.hash("unapprovedpassword")
    user = User(
        username="unapproved",
        email="unapproved@example.com",
        hashed_password=hashed_password,
        role=Role.user,
        is_approved=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def user_service(db):
    """UserServiceのインスタンスを提供"""
    return UserService(db)
