import enum
import json
from typing import Any, Dict, List

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ServerStatus(enum.Enum):
    stopped = "stopped"
    starting = "starting"
    running = "running"
    stopping = "stopping"
    error = "error"


class ServerType(enum.Enum):
    vanilla = "vanilla"
    forge = "forge"
    paper = "paper"


class Server(Base):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    minecraft_version = Column(String(20), nullable=False)
    server_type = Column(Enum(ServerType), nullable=False)
    status = Column(Enum(ServerStatus), default=ServerStatus.stopped)
    directory_path = Column(String(500), nullable=False)
    port = Column(Integer, default=25565)
    max_memory = Column(Integer, default=1024)  # MB
    max_players = Column(Integer, default=20)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner = relationship("User", back_populates="servers")
    template = relationship("Template", back_populates="servers")
    backups = relationship(
        "Backup", back_populates="server", cascade="all, delete-orphan"
    )
    configurations = relationship(
        "ServerConfiguration", back_populates="server", cascade="all, delete-orphan"
    )
    server_groups = relationship(
        "ServerGroup", back_populates="server", cascade="all, delete-orphan"
    )
    file_edit_history = relationship(
        "FileEditHistory", back_populates="server", cascade="all, delete-orphan"
    )
    backup_schedule = relationship(
        "BackupSchedule",
        back_populates="server",
        uselist=False,
        cascade="all, delete-orphan",
    )


class BackupType(enum.Enum):
    manual = "manual"
    scheduled = "scheduled"
    pre_update = "pre_update"


class BackupStatus(enum.Enum):
    creating = "creating"
    completed = "completed"
    failed = "failed"


class Backup(Base):
    __tablename__ = "backups"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    file_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger, nullable=False)  # bytes
    backup_type = Column(Enum(BackupType), default=BackupType.manual)
    status = Column(Enum(BackupStatus), default=BackupStatus.creating)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    server = relationship("Server", back_populates="backups")


class ServerConfiguration(Base):
    __tablename__ = "server_configurations"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    configuration_key = Column(String(100), nullable=False)
    configuration_value = Column(Text, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    server = relationship("Server", back_populates="configurations")

    __table_args__ = (UniqueConstraint("server_id", "configuration_key"),)


class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    minecraft_version = Column(String(20), nullable=False)
    server_type = Column(Enum(ServerType), nullable=False)
    configuration = Column(JSON, nullable=False)  # server.properties and other settings
    default_groups = Column(JSON)  # Default group attachments
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_public = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    creator = relationship("User", back_populates="templates")
    servers = relationship("Server", back_populates="template")

    def get_configuration(self) -> Dict[str, Any]:
        """Get configuration as Python dict"""
        if isinstance(self.configuration, str):
            return json.loads(self.configuration)
        return self.configuration or {}

    def set_configuration(self, config: Dict[str, Any]) -> None:
        """Set configuration from Python dict"""
        self.configuration = config

    def get_default_groups(self) -> Dict[str, List[int]]:
        """Get default groups as Python dict"""
        if isinstance(self.default_groups, str):
            return json.loads(self.default_groups)
        return self.default_groups or {"op_groups": [], "whitelist_groups": []}

    def set_default_groups(self, groups: Dict[str, List[int]]) -> None:
        """Set default groups from Python dict"""
        self.default_groups = groups
