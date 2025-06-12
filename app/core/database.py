from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# SQLite database URL (relative path file)
DATABASE_URL = settings.DATABASE_URL

# connect_args is necessary for SQLite (to avoid thread constraints)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

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
