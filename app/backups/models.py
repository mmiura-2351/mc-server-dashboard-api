from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ScheduleAction(str, PyEnum):
    """Backup schedule action types"""

    created = "created"
    updated = "updated"
    deleted = "deleted"
    executed = "executed"
    skipped = "skipped"


class BackupSchedule(Base):
    """Backup schedule configuration"""

    __tablename__ = "backup_schedules"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Key (Unique: 1 schedule per server)
    server_id = Column(
        Integer, ForeignKey("servers.id"), unique=True, nullable=False, index=True
    )

    # Schedule configuration
    interval_hours = Column(
        Integer,
        nullable=False,
        # CHECK constraint: 1 hour to 1 week (168 hours)
    )
    max_backups = Column(
        Integer,
        nullable=False,
        # CHECK constraint: 1 to 30 items
    )
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    only_when_running = Column(Boolean, default=True, nullable=False)

    # Execution state management
    last_backup_at = Column(DateTime, nullable=True)
    next_backup_at = Column(DateTime, nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relations
    server = relationship("Server", back_populates="backup_schedule")

    # CHECK constraints
    __table_args__ = (
        CheckConstraint(
            "interval_hours >= 1 AND interval_hours <= 168",
            name="check_interval_hours_range",
        ),
        CheckConstraint(
            "max_backups >= 1 AND max_backups <= 30", name="check_max_backups_range"
        ),
    )

    def __repr__(self):
        return f"<BackupSchedule(id={self.id}, server_id={self.server_id}, interval_hours={self.interval_hours}, enabled={self.enabled})>"


class BackupScheduleLog(Base):
    """Backup schedule operation log (for auditing)"""

    __tablename__ = "backup_schedule_logs"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False, index=True)
    action = Column(Enum(ScheduleAction), nullable=False, index=True)
    reason = Column(String(255), nullable=True)
    old_config = Column(JSON, nullable=True)
    new_config = Column(JSON, nullable=True)
    executed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relations
    server = relationship("Server")
    executed_by = relationship("User")

    # CHECK constraint is unnecessary as SQLAlchemy Enum automatically sets constraints

    def __repr__(self):
        return f"<BackupScheduleLog(id={self.id}, server_id={self.server_id}, action={self.action})>"
