"""SQLAlchemy implementation of `FileHistoryRepository`.

Implements `app.files.domain.ports.FileHistoryRepository`. The adapter
is the only layer that knows about the SQLAlchemy ORM and the
`FileEditHistory` columns; it converts ORM rows to/from
`FileHistoryEntity` so the application layer never sees ORM types.

Per the UnitOfWork pattern, repository methods **do not commit**. They
stage changes on the session and rely on the surrounding
`SqlAlchemyFilesUnitOfWork` (or the caller) to commit.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload

from app.files.domain.entities import (
    CreateHistoryCommand,
    FileHistoryEntity,
    FileHistoryStatsEntity,
)
from app.files.models import FileEditHistory


def _history_to_entity(row: FileEditHistory) -> FileHistoryEntity:
    """Convert an ORM row into a domain entity.

    Reads `row.editor.username` eagerly. Callers that need this field
    must load the row with `joinedload(FileEditHistory.editor)` so the
    access does not trigger a separate SELECT.
    """
    editor_username = row.editor.username if row.editor is not None else None
    return FileHistoryEntity(
        id=row.id,
        server_id=row.server_id,
        file_path=row.file_path,
        version_number=row.version_number,
        backup_file_path=row.backup_file_path,
        file_size=row.file_size,
        content_hash=row.content_hash,
        editor_user_id=row.editor_user_id,
        editor_username=editor_username,
        created_at=row.created_at,
        description=row.description,
    )


class SqlAlchemyFileHistoryRepository:
    """SQLAlchemy-backed implementation of the file-history
    persistence Port.

    Does not commit. Callers must drive transactions via
    `FilesUnitOfWork` (production) or by explicitly committing the
    session (legacy paths, while shims still exist).
    """

    def __init__(self, db: Session):
        self.db = db

    # ===================
    # Reads
    # ===================

    async def get_history_for_file(
        self, server_id: int, file_path: str, limit: int
    ) -> List[FileHistoryEntity]:
        rows = (
            self.db.query(FileEditHistory)
            .options(joinedload(FileEditHistory.editor))
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == file_path,
            )
            .order_by(desc(FileEditHistory.version_number))
            .limit(limit)
            .all()
        )
        return [_history_to_entity(r) for r in rows]

    async def get_version(
        self, server_id: int, file_path: str, version_number: int
    ) -> Optional[FileHistoryEntity]:
        row = (
            self.db.query(FileEditHistory)
            .options(joinedload(FileEditHistory.editor))
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == file_path,
                FileEditHistory.version_number == version_number,
            )
            .first()
        )
        return _history_to_entity(row) if row else None

    async def get_latest(
        self, server_id: int, file_path: str
    ) -> Optional[FileHistoryEntity]:
        row = (
            self.db.query(FileEditHistory)
            .options(joinedload(FileEditHistory.editor))
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == file_path,
            )
            .order_by(desc(FileEditHistory.version_number))
            .first()
        )
        return _history_to_entity(row) if row else None

    async def get_max_version_number(self, server_id: int, file_path: str) -> int:
        latest = (
            self.db.query(func.max(FileEditHistory.version_number))
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == file_path,
            )
            .scalar()
        )
        return latest or 0

    async def reserve_next_version_number(self, server_id: int, file_path: str) -> int:
        """Return the next available version number for the given key.

        Wraps `MAX(version_number) + 1` via `COALESCE` so an empty
        result set yields `1`. Caller must be inside an active UoW
        transaction; the surrounding UNIQUE constraint catches any
        race that slips between this read and the corresponding INSERT.
        """
        max_version = (
            self.db.query(func.coalesce(func.max(FileEditHistory.version_number), 0))
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == file_path,
            )
            .scalar()
        )
        return int(max_version or 0) + 1

    async def get_excess_versions(
        self, server_id: int, file_path: str, keep: int
    ) -> List[FileHistoryEntity]:
        rows = (
            self.db.query(FileEditHistory)
            .options(joinedload(FileEditHistory.editor))
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == file_path,
            )
            .order_by(desc(FileEditHistory.version_number))
            .offset(keep)
            .all()
        )
        return [_history_to_entity(r) for r in rows]

    async def get_versions_older_than(
        self, cutoff: datetime, server_id: Optional[int] = None
    ) -> List[FileHistoryEntity]:
        query = (
            self.db.query(FileEditHistory)
            .options(joinedload(FileEditHistory.editor))
            .filter(FileEditHistory.created_at < cutoff)
        )
        if server_id is not None:
            query = query.filter(FileEditHistory.server_id == server_id)
        rows = query.all()
        return [_history_to_entity(r) for r in rows]

    async def get_server_statistics(self, server_id: int) -> FileHistoryStatsEntity:
        stats = (
            self.db.query(
                func.count(FileEditHistory.id).label("total_versions"),
                func.count(func.distinct(FileEditHistory.file_path)).label("total_files"),
                func.sum(FileEditHistory.file_size).label("total_storage"),
                func.min(FileEditHistory.created_at).label("oldest_version"),
                func.max(FileEditHistory.created_at).label("newest_version"),
            )
            .filter(FileEditHistory.server_id == server_id)
            .first()
        )

        most_edited = (
            self.db.query(
                FileEditHistory.file_path,
                func.count(FileEditHistory.id).label("version_count"),
            )
            .filter(FileEditHistory.server_id == server_id)
            .group_by(FileEditHistory.file_path)
            .order_by(desc("version_count"))
            .first()
        )

        return FileHistoryStatsEntity(
            server_id=server_id,
            total_files_with_history=(stats.total_files if stats else 0) or 0,
            total_versions=(stats.total_versions if stats else 0) or 0,
            total_storage_used=(stats.total_storage if stats else 0) or 0,
            oldest_version_date=stats.oldest_version if stats else None,
            most_edited_file=most_edited.file_path if most_edited else None,
            most_edited_file_versions=(
                most_edited.version_count if most_edited else None
            ),
        )

    # ===================
    # Writes
    # ===================

    async def add(self, command: CreateHistoryCommand) -> FileHistoryEntity:
        row = FileEditHistory(
            server_id=command.server_id,
            file_path=command.file_path,
            version_number=command.version_number,
            backup_file_path=command.backup_file_path,
            file_size=command.file_size,
            content_hash=command.content_hash,
            editor_user_id=command.editor_user_id,
            description=command.description,
        )
        self.db.add(row)
        self.db.flush()
        # Populate the `editor` relation so `_history_to_entity` resolves
        # `editor_username` without a stray lazy SELECT. `refresh` issues
        # one targeted load instead of re-SELECTing the whole row.
        if row.editor_user_id is not None:
            self.db.refresh(row, attribute_names=["editor"])
        return _history_to_entity(row)

    async def delete_by_id(self, record_id: int) -> bool:
        row = (
            self.db.query(FileEditHistory).filter(FileEditHistory.id == record_id).first()
        )
        if row is None:
            return False
        self.db.delete(row)
        return True
