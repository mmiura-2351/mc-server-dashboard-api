from typing import Any, Dict

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# Database URL from settings
DATABASE_URL = settings.DATABASE_URL

# Build engine kwargs with explicit connection pool configuration
# (Issue #369). SQLite needs `check_same_thread=False` but does not
# support pool_size / max_overflow (it uses QueuePool(pool_size=5) by
# default, which is fine). Non-SQLite backends get full pool tuning.
engine_kwargs: Dict[str, Any] = {
    "connect_args": {"check_same_thread": False},
}

if not DATABASE_URL.startswith("sqlite"):
    # Remove SQLite-specific connect_args for other backends
    engine_kwargs.pop("connect_args")
    engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
    engine_kwargs["pool_recycle"] = settings.DB_POOL_RECYCLE

# pool_pre_ping is supported by all backends (including SQLite)
engine_kwargs["pool_pre_ping"] = settings.DB_POOL_PRE_PING

engine = create_engine(DATABASE_URL, **engine_kwargs)

# Set up database query monitoring
try:
    from app.middleware.database_monitoring import db_monitor

    db_monitor.setup_sqlalchemy_monitoring(engine)
except ImportError:
    # Monitoring not available, continue without it
    pass

# Create session local class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class (inheritance source for models)
Base = declarative_base()


# DB session acquisition function for Dependency (used for dependency injection in FastAPI)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
