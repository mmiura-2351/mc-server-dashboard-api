"""Legacy file-history-service facade.

Migrated from `app.services.file_history_service` under #228 PR 3. The
only remaining production consumer is the legacy
`file_management_service`, which passes its own DB session positionally.
The facade builds a one-shot `SqlAlchemyFilesUnitOfWork` +
`SqlAlchemyServerReadPort` per call.
"""

from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.files.adapters.uow import SqlAlchemyFilesUnitOfWork
from app.files.application.service import FileHistoryService
from app.servers.adapters.read_port import SqlAlchemyServerReadPort

__all__ = ["FileHistoryService", "file_history_service", "_LegacyFileHistoryFacade"]


class _LegacyFileHistoryFacade:
    """Adapts the new DI-shaped `FileHistoryService` to legacy callers
    that pass `db=Session` explicitly per call.

    This is intentionally a thin per-call factory rather than a long-lived
    service instance: a `SqlAlchemyFilesUnitOfWork` is bound to a single
    session, so reusing one across requests would be unsafe.
    """

    def __init__(
        self,
        history_base_dir: Path = Path("./file_history"),
        max_versions_per_file: int = 50,
        auto_cleanup_days: int = 30,
    ):
        self.history_base_dir = history_base_dir
        self.max_versions_per_file = max_versions_per_file
        self.auto_cleanup_days = auto_cleanup_days

    def _build(self, db: Session) -> FileHistoryService:
        return FileHistoryService(
            uow=SqlAlchemyFilesUnitOfWork(db=db),
            server_read=SqlAlchemyServerReadPort(db),
            history_base_dir=self.history_base_dir,
            max_versions_per_file=self.max_versions_per_file,
            auto_cleanup_days=self.auto_cleanup_days,
        )

    async def create_version_backup(
        self,
        server_id: int,
        file_path: str,
        content: str,
        user_id: Optional[int] = None,
        description: Optional[str] = None,
        db: Optional[Session] = None,
    ):
        if db is None:
            raise ValueError(
                "Database session is required for security-critical file "
                "backup operations"
            )
        return await self._build(db).create_version_backup(
            server_id=server_id,
            file_path=file_path,
            content=content,
            user_id=user_id,
            description=description,
        )


file_history_service = _LegacyFileHistoryFacade()
