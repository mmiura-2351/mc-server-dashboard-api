import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import Mock
from app.main import app
from app.core.database import get_db, Base
from app.users.models import User, Role
from app.services.user import UserService
from passlib.context import CryptContext

# テスト用のインメモリSQLiteデータベース
import os
import tempfile

# 一時ファイルを使用してプロセス間での共有を可能にする
test_db_path = os.path.join(tempfile.gettempdir(), "test_mc_server.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{test_db_path}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    echo=False
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# テスト用の軽量なパスワードハッシュ化（高速化のため）
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def pytest_sessionfinish(session, exitstatus):
    """テストセッション終了時にテストデータベースファイルを削除"""
    try:
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
    except Exception:
        pass


@pytest.fixture(scope="function")
def db():
    # テーブルを作成
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        # セッションをクローズ
        db.close()
        # 全テーブルをクリア（より軽量）
        with engine.connect() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
            conn.commit()


@pytest.fixture(scope="session")
def base_client():
    """Base TestClient for session scope"""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def client(db, base_client):
    # dbフィクスチャを依存関係に追加してテーブルが作成されるようにする
    yield base_client


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


@pytest.fixture
def admin_headers(client, admin_user):
    """管理者用認証ヘッダーを生成"""
    login_data = {
        "username": admin_user.username,
        "password": "adminpassword"
    }
    response = client.post("/api/v1/auth/token", data=login_data)
    if response.status_code != 200:
        print(f"Login failed: {response.status_code} - {response.text}")
    response_data = response.json()
    token = response_data["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(client, test_user):
    """一般ユーザー用認証ヘッダーを生成"""
    login_data = {
        "username": test_user.username,
        "password": "testpassword"
    }
    response = client.post("/api/v1/auth/token", data=login_data)
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_server(db, admin_user):
    """テスト用サーバーを作成"""
    from app.servers.models import Server, ServerType, ServerStatus
    server = Server(
        name="Test Server",
        description="A test server",
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        status=ServerStatus.stopped,
        directory_path="./servers/1",
        port=25565,
        max_memory=1024,
        max_players=20,
        owner_id=admin_user.id
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    return server


@pytest.fixture
def mock_request():
    """Mock FastAPI Request object for testing audit functions"""
    mock_req = Mock()
    mock_req.url.path = "/test/endpoint"
    mock_req.method = "POST"
    mock_req.headers = {
        "User-Agent": "TestClient/1.0",
        "X-Forwarded-For": "192.168.1.100",
    }
    mock_req.query_params = {}
    mock_req.client.host = "192.168.1.100"
    mock_req.state = Mock()
    return mock_req
