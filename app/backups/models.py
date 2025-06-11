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
    """バックアップスケジュールのアクション種別"""

    created = "created"
    updated = "updated"
    deleted = "deleted"
    executed = "executed"
    skipped = "skipped"


class BackupSchedule(Base):
    """バックアップスケジュール設定"""

    __tablename__ = "backup_schedules"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Key (Unique: 1サーバー1スケジュール)
    server_id = Column(
        Integer, ForeignKey("servers.id"), unique=True, nullable=False, index=True
    )

    # スケジュール設定
    interval_hours = Column(
        Integer,
        nullable=False,
        # CHECK制約: 1時間〜1週間（168時間）
    )
    max_backups = Column(
        Integer,
        nullable=False,
        # CHECK制約: 1〜30個
    )
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    only_when_running = Column(Boolean, default=True, nullable=False)

    # 実行状態管理
    last_backup_at = Column(DateTime, nullable=True)
    next_backup_at = Column(DateTime, nullable=True, index=True)

    # タイムスタンプ
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # リレーション
    server = relationship("Server", back_populates="backup_schedule")

    # CHECK制約
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
    """バックアップスケジュール操作ログ（監査用）"""

    __tablename__ = "backup_schedule_logs"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False, index=True)
    action = Column(Enum(ScheduleAction), nullable=False, index=True)
    reason = Column(String(255), nullable=True)
    old_config = Column(JSON, nullable=True)
    new_config = Column(JSON, nullable=True)
    executed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # リレーション
    server = relationship("Server")
    executed_by = relationship("User")

    # SQLAlchemyのEnumで自動的に制約が設定されるため、CHECK制約は不要

    def __repr__(self):
        return f"<BackupScheduleLog(id={self.id}, server_id={self.server_id}, action={self.action})>"
