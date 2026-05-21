"""Backward-compatibility shim for the migrated backup service.

The real implementation lives at `app.backups.application.service` and
is wired in production via `app.backups.api.dependencies.get_backup_service`.

The legacy `backup_service` singleton at this module path is preserved
for callers that still construct it manually (`tests/test_security.py`
instantiates `BackupService()` with no arguments). The facade builds a
one-shot `SqlAlchemyBackupsUnitOfWork` + `SqlAlchemyServerReadPort`
per call from the explicit `db=` argument legacy callers pass.

TODO(#228): once `test_security.py` and any other manual-construction
callsites migrate to DI, delete this file.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.orm import Session

from app.backups.application.file_service import BackupFileService
from app.backups.application.resource_monitor import ResourceMonitor
from app.backups.application.service import (
    BackupService as _ApplicationBackupService,
)
from app.core.exceptions import (
    BackupNotFoundException,
    DatabaseOperationException,
    FileOperationException,
    ServerNotFoundException,
)
from app.servers.adapters.read_port import SqlAlchemyServerReadPort

if TYPE_CHECKING:
    from fastapi import UploadFile

    from app.servers.models import BackupType

__all__ = [
    "BackupService",
    "BackupFileService",
    "ResourceMonitor",
    "BackupValidationService",
    "backup_service",
    "BackupNotFoundException",
    "FileOperationException",
    "DatabaseOperationException",
    "ServerNotFoundException",
]


def _build(db: Session) -> _ApplicationBackupService:
    """Build a per-call `BackupService` bound to `db`."""
    from app.backups.adapters.uow import SqlAlchemyBackupsUnitOfWork

    return _ApplicationBackupService(
        uow=SqlAlchemyBackupsUnitOfWork(db=db),
        server_read=SqlAlchemyServerReadPort(db),
    )


class _LegacyBackupFacade:
    """Narrow legacy facade for `tests/test_security.py`.

    Tests instantiate `BackupService()` (zero-arg) and patch
    `BackupValidationService.validate_server_for_backup` to inject a
    mock server. The facade preserves that surface — it accepts the
    same kwargs the legacy class did (notably `db=Session`) so the
    upload-security path stays patchable.
    """

    def __init__(self, backups_directory: Path = Path("backups")):
        self.backups_directory = Path(backups_directory)
        # The legacy class also instantiated these as attributes
        self.file_service = BackupFileService(self.backups_directory)
        self.validation_service = BackupValidationService()

    async def create_backup(
        self,
        server_id: int,
        name: str,
        db: Session,
        description: Optional[str] = None,
        backup_type: "BackupType" = None,
    ) -> Any:
        if db is None:
            raise ValueError("Database session is required for secure backup operations")
        from app.servers.models import BackupType as _BackupType

        return await _build(db).create_backup(
            server_id=server_id,
            name=name,
            description=description,
            backup_type=backup_type or _BackupType.manual,
        )

    async def restore_backup(
        self, backup_id: int, db: Session, server_id: Optional[int] = None
    ) -> bool:
        if db is None:
            raise ValueError("Database session is required for secure restore operations")
        return await _build(db).restore_backup(backup_id=backup_id, server_id=server_id)

    async def delete_backup(self, backup_id: int, db: Session) -> bool:
        return await _build(db).delete_backup(backup_id=backup_id)

    async def upload_backup(
        self,
        server_id: int,
        file: "UploadFile",
        db: Session,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Any:
        if db is None:
            raise ValueError("Database session is required for secure backup upload")
        svc = _build(db)
        # Honour the legacy zero-arg constructor's `backups_directory`
        # override (test_security.py rewrites it to a tmp path).
        svc.backups_directory = self.backups_directory
        svc._file_service = self.file_service
        return await svc.upload_backup(
            server_id=server_id, file=file, name=name, description=description
        )

    async def create_scheduled_backup(self, server_id: int, db: Session) -> Optional[Any]:
        return await _build(db).create_scheduled_backup(server_id=server_id)


class BackupValidationService:
    """Compat shim retained for `tests/test_security.py` patches.

    The legacy service had four static validation helpers. The new
    application layer absorbs the same checks inline (via
    `ServerReadPort.get` + status guards), but the test at
    `tests/test_security.py:555` patches
    `BackupValidationService.validate_server_for_backup`, so the
    surface is preserved here as a thin shim.
    """

    @staticmethod
    def validate_server_for_backup(server_id: int, db: Session) -> Any:
        raise NotImplementedError(
            "BackupValidationService is a legacy shim; production callers "
            "should depend on `BackupService` via "
            "`Depends(get_backup_service)`, which validates via "
            "`ServerReadPort.get`."
        )

    @staticmethod
    def validate_backup_exists(backup_id: int, db: Session) -> Any:
        raise NotImplementedError(
            "BackupValidationService is a legacy shim; production callers "
            "should depend on `BackupService` via "
            "`Depends(get_backup_service)`, which validates via "
            "`BackupRepository.get`."
        )


# Public aliases: legacy callers that construct `BackupService()` get
# the facade. The new DI-shaped service lives at
# `app.backups.application.service.BackupService` for migrated code.
BackupService = _LegacyBackupFacade
backup_service = _LegacyBackupFacade()
