"""Minimal `ServerReadPort` adapter (seed for #154-8).

Wraps a SQLAlchemy `Session` and surfaces the single method declared
on `app.servers.domain.ports.ServerReadPort`. Will be expanded — and
probably restructured — under Issue #228.
"""

from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.servers.domain.entities import ServerEntity
from app.servers.models import Server


class SqlAlchemyServerReadPort:
    """`ServerReadPort` backed by SQLAlchemy."""

    def __init__(self, db: Session):
        self._db = db

    async def get_directory_path(self, server_id: int) -> Optional[str]:
        # Primary-key lookup; `one_or_none` documents the intent that at
        # most one row can match, matching the Port's `Optional[str]`.
        row = (
            self._db.query(Server.directory_path)
            .filter(Server.id == server_id)
            .one_or_none()
        )
        if row is None:
            return None
        return row.directory_path

    async def get(self, server_id: int) -> Optional[ServerEntity]:
        """Return a minimal read-only `ServerEntity` for the given id.

        Soft-deleted rows (`is_deleted=True`) are excluded — they are
        not valid sources for template extraction.

        TBD(#154-8): the surface here is intentionally minimal. The full
        `ServerEntity` (with relationships, status, owner, etc.) lands
        with the servers-domain refactor in #228.
        """
        row = (
            self._db.query(Server)
            .filter(and_(Server.id == server_id, Server.is_deleted.is_(False)))
            .one_or_none()
        )
        if row is None:
            return None
        return ServerEntity(
            id=row.id,
            name=row.name,
            directory_path=row.directory_path,
            minecraft_version=row.minecraft_version,
            server_type=row.server_type,
            port=row.port,
            max_memory=row.max_memory,
            max_players=row.max_players,
            owner_id=row.owner_id,
        )
