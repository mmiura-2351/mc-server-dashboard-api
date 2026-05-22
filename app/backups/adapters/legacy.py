"""Legacy backup-service facade preserved for historical security tests.

Originally retained for `tests/test_security.py`; after the Issue #170 split
the surviving callers live in `tests/unit/backups/test_file_service_security.py`
and `tests/unit/backups/test_legacy_shim.py`. They instantiate
`BackupService()` with no arguments and patch
`BackupValidationService.validate_server_for_backup` to inject a mock
server. The facade builds a one-shot `SqlAlchemyBackupsUnitOfWork`
+ `SqlAlchemyServerReadPort` per call from the explicit `db=` argument
the legacy caller passes.

Migrated from `app.services.backup_service` under #228 PR 3. The legacy
shim path was removed; new code should depend on
`Depends(get_backup_service)` to receive a per-request
`app.backups.application.service.BackupService`.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.orm import Session

from app.backups.application.file_service import BackupFileService
from app.backups.application.resource_monitor import ResourceMonitor  # noqa: F401
from app.backups.application.service import (
    BackupService as _ApplicationBackupService,
)
from app.core.exceptions import (
    BackupNotFoundException,  # noqa: F401
    DatabaseOperationException,  # noqa: F401
    FileOperationException,  # noqa: F401
    ServerNotFoundException,  # noqa: F401
)
from app.servers.adapters.read_port import SqlAlchemyServerReadPort

if TYPE_CHECKING:
    from fastapi import UploadFile

    from app.servers.domain.value_objects import BackupType

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
    "_LegacyBackupFacade",
]


def _build(db: Session) -> _ApplicationBackupService:
    """Build a per-call `BackupService` bound to `db`."""
    from app.backups.adapters.uow import SqlAlchemyBackupsUnitOfWork

    return _ApplicationBackupService(
        uow=SqlAlchemyBackupsUnitOfWork(db=db),
        server_read=SqlAlchemyServerReadPort(db),
    )


class _LegacyBackupFacade:
    """Narrow legacy facade for historical security tests.

    After Issue #170 the surviving callers live in
    `tests/unit/backups/test_file_service_security.py` and
    `tests/unit/backups/test_legacy_shim.py`. Tests instantiate
    `BackupService()` (zero-arg) and patch
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
        backup_type: "BackupType | None" = None,
    ) -> Any:
        if db is None:
            raise ValueError("Database session is required for secure backup operations")
        from app.servers.domain.value_objects import BackupType as _BackupType

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
        # override (the file-service-security test rewrites it to a tmp path).
        svc.backups_directory = self.backups_directory
        svc._file_service = self.file_service
        return await svc.upload_backup(
            server_id=server_id, file=file, name=name, description=description
        )

    async def create_scheduled_backup(self, server_id: int, db: Session) -> Optional[Any]:
        return await _build(db).create_scheduled_backup(server_id=server_id)


class BackupValidationService:
    """Compat shim retained for historical security-test patches.

    The legacy service had four static validation helpers. The new
    application layer absorbs the same checks inline (via
    `ServerReadPort.get` + status guards), but the historical test at
    `tests/test_security.py` (now split under Issue #170 into
    `tests/unit/backups/test_file_service_security.py` and
    `tests/unit/backups/test_legacy_shim.py`) patches
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
