from sqlalchemy import (
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
from app.servers.domain.value_objects import (
    BackupStatus,
    BackupType,
    ServerStatus,
    ServerType,
)

__all__ = [
    "Backup",
    "BackupStatus",
    "BackupType",
    "Server",
    "ServerConfiguration",
    "ServerStatus",
    "ServerType",
]


class Server(Base):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    minecraft_version = Column(String(20), nullable=False)
    server_type: Column[ServerType] = Column(Enum(ServerType), nullable=False)
    status: Column[ServerStatus] = Column(
        Enum(ServerStatus), default=ServerStatus.stopped
    )
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


class Backup(Base):
    __tablename__ = "backups"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    file_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger, nullable=False)  # bytes
    backup_type: Column[BackupType] = Column(Enum(BackupType), default=BackupType.manual)
    status: Column[BackupStatus] = Column(
        Enum(BackupStatus), default=BackupStatus.creating
    )
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


# NOTE: The `Template` ORM class was relocated to `app.templates.models`
# in Issue #255. The `Server.template` relationship above uses a
# string-based class reference, which SQLAlchemy resolves at
# mapper-configuration time; `app/templates/__init__.py` eagerly imports
# `app.templates.models` so the class is registered before
# `Base.metadata.create_all()` runs.
