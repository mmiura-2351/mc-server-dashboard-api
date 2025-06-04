from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# SQLiteのデータベースURL（相対パスのファイル）
DATABASE_URL = settings.DATABASE_URL

# connect_argsはSQLiteの場合に必要（スレッド制約を回避）
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# セッションローカルクラスの作成
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ベースクラス（モデルの継承元）
Base = declarative_base()


# Dependency用のDBセッション取得関数（FastAPIで依存注入に使う）
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
