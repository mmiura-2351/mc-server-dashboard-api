# テスト用のインメモリSQLiteデータベース
import os
import shutil
import tempfile


# Worker固有のデータベースファイルを使用して並列実行時の分離を確保
def get_worker_db_path():
    """Get worker-specific database path for parallel execution isolation."""
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    return os.path.join(tempfile.gettempdir(), f"test_mc_server_{worker_id}.db")


# IMPORTANT: set DATABASE_URL BEFORE any `from app.*` import so that
# `app.core.database.engine` and `app.main` lifespan startup target the
# worker-specific SQLite file. Without this, every xdist worker hits the
# shared `./app.db` from `.env` and `Base.metadata.create_all` races into
# "database is locked" errors. See Issue #210.
test_db_path = get_worker_db_path()
os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path}"

from unittest.mock import Mock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.user import UserService  # noqa: E402
from app.users.models import Role, User  # noqa: E402

SQLALCHEMY_DATABASE_URL = f"sqlite:///{test_db_path}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    echo=False,
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
    """
    テストセッション終了時にworker固有のテストデータベースファイルを削除
    Race conditionを避けるため、各workerが自分のファイルのみを削除
    """
    # Dispose the shared SQLAlchemy engine so its pooled sqlite connections are
    # closed deterministically rather than reaped by GC (which emits
    # ResourceWarning under `-W error::ResourceWarning`).
    try:
        engine.dispose()
    except Exception:
        pass
    try:
        current_worker_db = get_worker_db_path()
        if os.path.exists(current_worker_db):
            os.remove(current_worker_db)
    except Exception as e:
        # エラーをログに記録するが、テスト結果には影響させない
        import warnings

        warnings.warn(f"Failed to cleanup test database {current_worker_db}: {e}")


def _java_available() -> bool:
    """Return True when a `java` executable is reachable on PATH."""
    return shutil.which("java") is not None


def pytest_collection_modifyitems(config, items):
    """Auto-skip `@pytest.mark.requires_java` tests when no JRE is on PATH."""
    if _java_available():
        return
    skip_marker = pytest.mark.skip(reason="requires_java: no JRE on PATH")
    for item in items:
        if "requires_java" in item.keywords:
            item.add_marker(skip_marker)


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


@pytest.fixture(scope="function")
def client(db):
    """
    Function-scoped TestClient to ensure proper isolation between tests
    in parallel execution. Each test gets a fresh client instance.
    """
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
def operator_user(db):
    """テスト用オペレーターユーザーを作成"""
    hashed_password = pwd_context.hash("operatorpassword")
    user = User(
        username="operator",
        email="operator@example.com",
        hashed_password=hashed_password,
        role=Role.operator,
        is_approved=True,
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
    login_data = {"username": admin_user.username, "password": "adminpassword"}
    response = client.post("/api/v1/auth/token", data=login_data)
    if response.status_code != 200:
        print(f"Login failed: {response.status_code} - {response.text}")
    response_data = response.json()
    token = response_data["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(client, test_user):
    """一般ユーザー用認証ヘッダーを生成"""
    login_data = {"username": test_user.username, "password": "testpassword"}
    response = client.post("/api/v1/auth/token", data=login_data)
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_server(db, admin_user):
    """テスト用サーバーを作成"""
    from app.servers.models import Server, ServerStatus, ServerType

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
        owner_id=admin_user.id,
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
