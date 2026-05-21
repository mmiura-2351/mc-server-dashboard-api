"""Minimal `ServerReadPort` adapter (seed for #154-8).

Wraps a SQLAlchemy `Session` and surfaces the single method declared
on `app.servers.domain.ports.ServerReadPort`. Will be expanded — and
probably restructured — under Issue #228.
"""

from typing import Optional

from sqlalchemy.orm import Session

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
