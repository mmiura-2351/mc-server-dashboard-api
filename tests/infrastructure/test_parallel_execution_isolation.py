"""
並列実行時のテスト分離を検証するテスト
"""
import os
import tempfile
from tests.conftest import get_worker_db_path


def test_worker_db_isolation():
    """Worker固有のデータベースパスが正しく分離されていることを確認"""
    db_path = get_worker_db_path()
    
    # パスがworker固有であることを確認
    assert "test_mc_server_" in db_path
    assert db_path.endswith(".db")
    
    # 一時ディレクトリ内にあることを確認
    temp_dir = tempfile.gettempdir()
    assert db_path.startswith(temp_dir)


def test_database_file_creation(db):
    """データベースファイルが適切に作成されることを確認"""
    db_path = get_worker_db_path()
    
    # データベースファイルが存在することを確認
    assert os.path.exists(db_path)
    
    # データベースに接続できることを確認
    assert db is not None
    assert hasattr(db, 'execute')


def test_test_isolation_simple_data(db):
    """テスト間でのデータ分離を確認（シンプルテスト1）"""
    from app.users.models import User, Role
    from passlib.context import CryptContext
    
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)
    
    # テストユーザーを作成
    test_user = User(
        username="isolation_test_1",
        email="test1@isolation.com",
        hashed_password=pwd_context.hash("password"),
        role=Role.user,
        is_approved=True,
    )
    db.add(test_user)
    db.commit()
    
    # ユーザーが存在することを確認
    found_user = db.query(User).filter(User.username == "isolation_test_1").first()
    assert found_user is not None
    assert found_user.email == "test1@isolation.com"


def test_test_isolation_different_data(db):
    """テスト間でのデータ分離を確認（シンプルテスト2）"""
    from app.users.models import User, Role
    from passlib.context import CryptContext
    
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)
    
    # 異なるテストユーザーを作成
    test_user = User(
        username="isolation_test_2",
        email="test2@isolation.com",
        hashed_password=pwd_context.hash("password"),
        role=Role.admin,
        is_approved=True,
    )
    db.add(test_user)
    db.commit()
    
    # 前のテストのユーザーが存在しないことを確認（分離されている）
    previous_user = db.query(User).filter(User.username == "isolation_test_1").first()
    assert previous_user is None
    
    # 現在のユーザーが存在することを確認
    current_user = db.query(User).filter(User.username == "isolation_test_2").first()
    assert current_user is not None
    assert current_user.role == Role.admin