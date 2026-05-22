"""Unit-level regression for the file-history UNIQUE-violation retry path.

Complements
:func:`tests.integration.files.test_toctou.test_concurrent_create_version_backup_separate_sessions_fire_retry`
— the integration test proves the retry path engages under real
SQLite contention, but it costs tens of seconds because contended
writers serialise at the dialect level. This file pins the same
behaviour against the in-memory fakes in
:mod:`tests.unit.files.fakes` so the retry contract is verified in
~milliseconds and runs in the pre-commit smoke lane (no
``@pytest.mark.slow``).

Strategy:
    1. Subclass :class:`FakeFileHistoryRepository` so its ``add``
       raises a synthetic :class:`sqlalchemy.exc.IntegrityError`
       carrying the SQLite-shaped column-list message exactly once,
       then defers to the real in-memory implementation. This is the
       fake-side analogue of the SQLite monkeypatch in
       :func:`tests.integration.files.test_toctou.test_toctou_retry_fires_on_sqlite_unique_violation`.
    2. Drive :meth:`FileHistoryService.create_version_backup` and
       assert that
       (a) the call succeeds (retry recovered),
       (b) ``add`` was invoked exactly twice (one failure + one
       success — no infinite loop, no over-retry), and
       (c) the persisted row carries ``version_number=1`` (the retry
       reservation collapses back to the next free slot because the
       failed first attempt rolled back).
"""

import logging
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.files.application.service import FileHistoryService
from app.files.domain.entities import CreateHistoryCommand, FileHistoryEntity
from tests.unit.files.fakes import (
    FakeFileHistoryRepository,
    FakeFilesUnitOfWork,
    FakeServerReadPort,
)


class _FailOnceFileHistoryRepository(FakeFileHistoryRepository):
    """Fake that raises a SQLite-shaped UNIQUE :class:`IntegrityError`
    on the first ``add`` call, then delegates to the real fake.

    The error text deliberately matches the column-list shape SQLite
    emits — ``UNIQUE constraint failed:
    file_edit_history.server_id, file_edit_history.file_path,
    file_edit_history.version_number`` — so the production-side
    detector :func:`app.files.application.service._is_version_unique_violation`
    must classify it as a version-collision (and not a generic
    integrity error that surfaces to the caller).
    """

    _UNIQUE_MSG = (
        "UNIQUE constraint failed: "
        "file_edit_history.server_id, "
        "file_edit_history.file_path, "
        "file_edit_history.version_number"
    )

    def __init__(self) -> None:
        super().__init__()
        self.add_calls = 0

    async def add(self, command: CreateHistoryCommand) -> FileHistoryEntity:
        self.add_calls += 1
        if self.add_calls == 1:
            # SQLAlchemy's IntegrityError carries the driver-level
            # exception as `orig`; the production detector inspects
            # both `str(e.orig)` and `str(e)`, so it is enough to
            # stash the SQLite-shaped message as `orig`.
            raise IntegrityError(
                statement="INSERT INTO file_edit_history ...",
                params={},
                orig=Exception(self._UNIQUE_MSG),
            )
        return await super().add(command)


@pytest.fixture
def fail_once_repo() -> _FailOnceFileHistoryRepository:
    return _FailOnceFileHistoryRepository()


@pytest.fixture
def service(
    fail_once_repo: _FailOnceFileHistoryRepository,
    tmp_path: Path,
) -> FileHistoryService:
    return FileHistoryService(
        uow=FakeFilesUnitOfWork(files_history=fail_once_repo),
        server_read=FakeServerReadPort({1: "./servers/1"}),
        history_base_dir=tmp_path / "file_history",
        max_versions_per_file=10,
        auto_cleanup_days=30,
    )


@pytest.mark.asyncio
async def test_retry_recovers_from_single_unique_violation(
    service: FileHistoryService,
    fail_once_repo: _FailOnceFileHistoryRepository,
    caplog,
):
    """``create_version_backup`` retries past a one-shot
    SQLite-shaped UNIQUE failure and persists exactly one row.

    Together with the integration sibling this pins the retry
    contract on **both** the real SQLAlchemy path and the in-memory
    fake path, so future refactors that move the retry loop or
    reshape the detector cannot quietly break the recovery
    behaviour.
    """
    with caplog.at_level(logging.WARNING, logger="app.files.application.service"):
        entity = await service.create_version_backup(
            server_id=1,
            file_path="server.properties",
            content="content-v1\n",
            user_id=42,
            description="first",
        )

    assert entity is not None, (
        "Retry should have succeeded; got None (= 'content unchanged' "
        "short-circuit), which is impossible on an empty history."
    )
    assert entity.version_number == 1, (
        "Second attempt re-reserves the next free version number — on "
        "an empty file this is still 1 because the first attempt rolled "
        "back."
    )
    assert fail_once_repo.add_calls == 2, (
        f"Expected exactly two add() calls (1 collision + 1 retry); "
        f"got {fail_once_repo.add_calls}. A higher count would mean "
        f"the retry loop is over-retrying; a lower one would mean the "
        f"first failure was not actually classified as a UNIQUE "
        f"violation."
    )

    toctou_warnings = [
        r
        for r in caplog.records
        if r.name == "app.files.application.service"
        and r.levelno == logging.WARNING
        and "TOCTOU collision" in r.getMessage()
    ]
    assert len(toctou_warnings) == 1, (
        f"Expected exactly one TOCTOU collision warning matching the "
        f"single induced failure; got {len(toctou_warnings)}: "
        f"{[r.getMessage() for r in toctou_warnings]}."
    )


@pytest.mark.asyncio
async def test_non_version_integrity_error_is_not_retried(
    tmp_path: Path,
):
    """A non-version :class:`IntegrityError` (e.g. a foreign-key
    failure) must bubble out as a domain exception instead of being
    silently retried.

    This pins the negative side of the
    :func:`app.files.application.service._is_version_unique_violation`
    classifier: misclassifying an arbitrary integrity error as a
    version collision would cause spurious retries (and at worst
    silently lose data after the third attempt also fails).
    """
    from app.core.exceptions import FileOperationException

    class _UnrelatedIntegrityRepo(FakeFileHistoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.add_calls = 0

        async def add(self, command: CreateHistoryCommand) -> FileHistoryEntity:
            self.add_calls += 1
            raise IntegrityError(
                statement="INSERT INTO file_edit_history ...",
                params={},
                # Unrelated message — does not match the version-collision
                # detector on either the index-name or column-list branch.
                orig=Exception("FOREIGN KEY constraint failed"),
            )

    repo = _UnrelatedIntegrityRepo()
    service = FileHistoryService(
        uow=FakeFilesUnitOfWork(files_history=repo),
        server_read=FakeServerReadPort({1: "./servers/1"}),
        history_base_dir=tmp_path / "file_history",
        max_versions_per_file=10,
        auto_cleanup_days=30,
    )

    # The service wraps unexpected errors in FileOperationException
    # (see `create_version_backup`'s outer try/except), so we assert on
    # the wrapper rather than IntegrityError directly.
    with pytest.raises(FileOperationException):
        await service.create_version_backup(
            server_id=1,
            file_path="server.properties",
            content="content-v1\n",
            user_id=42,
        )

    assert repo.add_calls == 1, (
        f"Non-version IntegrityError must not be retried; got "
        f"{repo.add_calls} add() calls."
    )
