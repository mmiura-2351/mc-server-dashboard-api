"""SQLAlchemy ORM models for the templates domain.

The `Template` ORM was originally co-located with the servers domain in
`app/servers/models.py`. Moving it here (Issue #255) restores the
domain-aligned layout introduced by the hexagonal refactor in #225.

Note on mapper configuration:
    `app.servers.models.Server` declares
    `template = relationship("Template", back_populates="servers")`
    using a string-based class reference. SQLAlchemy resolves that
    reference at mapper-configuration time, so this module must be
    imported *before* the first mapper-config trigger
    (i.e. before `Base.metadata.create_all()` in `app.main`).

    `app/templates/__init__.py` eagerly imports this module
    (`from . import models  # noqa: F401`) so any code that imports the
    `app.templates` package — including `from app.templates.router
    import router` in `app.main` — guarantees the class is registered
    in time. The pre-existing chain `templates.router → application →
    adapters.repository` also imports this module, providing belt-
    and-braces coverage.
"""

import json
from typing import Any, Dict, List

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.servers.domain.value_objects import ServerType

__all__ = ["Template"]


class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    minecraft_version = Column(String(20), nullable=False)
    server_type: Column[ServerType] = Column(Enum(ServerType), nullable=False)
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
