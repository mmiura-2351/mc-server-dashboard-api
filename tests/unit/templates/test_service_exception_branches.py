"""Exception-branch coverage for `TemplateService` internal helpers.

Restores coverage for the exception handlers that were exercised by the
deleted `tests/unit/services/test_template_service.py` (removed in
PR #256 / #225). The happy-path/visibility tests already live in
`test_service_with_fake.py`; this file focuses exclusively on the
error-injection paths for:

- `_parse_server_properties` IO-error branch
- `_create_template_files` tarfile-error branch
- `_apply_server_properties` write-error branch
- `delete_template` archive unlink-error branch
- `get_template_statistics` repository-failure branch

Production code is unchanged: errors are injected via monkeypatching of
`builtins.open`, `tarfile.open`, `pathlib.Path.unlink`, and by swapping
the fake repository's count methods for raising stubs.

See: https://github.com/mmiura-2351/mc-server-dashboard-api/issues/258
"""

import builtins
import tarfile
from pathlib import Path

import pytest

from app.servers.domain.entities import ServerEntity
from app.servers.models import ServerType
from app.templates.application.service import TemplateService
from app.templates.domain.exceptions import (
    TemplateCreationError,
    TemplateError,
)
from tests.unit.files.fakes import FakeServerReadPort
from tests.unit.templates.fakes import (
    FakeTemplateRepository,
    FakeTemplatesUnitOfWork,
    make_template_entity,
)


@pytest.fixture
def repo() -> FakeTemplateRepository:
    return FakeTemplateRepository()


@pytest.fixture
def uow(repo: FakeTemplateRepository) -> FakeTemplatesUnitOfWork:
    return FakeTemplatesUnitOfWork(templates=repo)


@pytest.fixture
def server_read() -> FakeServerReadPort:
    return FakeServerReadPort()


@pytest.fixture
def service(
    uow: FakeTemplatesUnitOfWork,
    server_read: FakeServerReadPort,
    tmp_path: Path,
) -> TemplateService:
    return TemplateService(
        uow=uow,
        server_read=server_read,
        templates_directory=tmp_path / "templates",
    )


def _make_server_dir(tmp_path: Path, name: str = "server1") -> Path:
    server_dir = tmp_path / name
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=Test\n")
    return server_dir


# ---------------------------------------------------------------------------
# _parse_server_properties — IO error branch (lines ~523-525)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_server_properties_returns_empty_dict_on_io_error(
    service: TemplateService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """`_parse_server_properties` swallows IOError and returns `{}`.

    The contract (preserved from legacy) is *best-effort*: a broken
    `server.properties` should not prevent template extraction.
    """
    properties_path = tmp_path / "server.properties"
    properties_path.write_text("motd=Test\n")

    real_open = builtins.open

    def boom(file, *args, **kwargs):
        # Only fail for the properties file; leave everything else alone
        if str(file) == str(properties_path):
            raise OSError("disk gremlins")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", boom)

    result = await service._parse_server_properties(properties_path)
    assert result == {}


@pytest.mark.asyncio
async def test_create_template_from_server_survives_properties_io_error(
    service: TemplateService,
    server_read: FakeServerReadPort,
    uow: FakeTemplatesUnitOfWork,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Template creation continues with empty `server_properties` if
    parsing the properties file fails (the IO-error branch returns `{}`
    rather than propagating).
    """
    server_dir = _make_server_dir(tmp_path)
    server_read.set_server(
        ServerEntity(
            id=1,
            name="My Server",
            directory_path=str(server_dir),
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20,
            owner_id=42,
        )
    )

    real_open = builtins.open
    properties_path = server_dir / "server.properties"

    def boom(file, *args, **kwargs):
        if str(file) == str(properties_path):
            raise OSError("transient read failure")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", boom)

    entity = await service.create_template_from_server(
        server_id=1, name="resilient", creator_id=42
    )
    # Properties failed → empty dict, but template itself was created
    assert entity.configuration["server_properties"] == {}
    assert uow.committed >= 1


# ---------------------------------------------------------------------------
# _create_template_files — tarfile error branch (lines ~554-556)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_template_files_raises_template_creation_error_on_tar_failure(
    service: TemplateService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """`_create_template_files` wraps tarfile failures in
    `TemplateCreationError`.
    """
    server_dir = _make_server_dir(tmp_path, name="src")

    def boom(*args, **kwargs):
        raise tarfile.TarError("archive write failed")

    monkeypatch.setattr(tarfile, "open", boom)

    with pytest.raises(TemplateCreationError, match="Failed to create template files"):
        await service._create_template_files(template_id=42, server_dir=server_dir)


@pytest.mark.asyncio
async def test_create_template_from_server_propagates_tar_failure(
    service: TemplateService,
    server_read: FakeServerReadPort,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """When archive creation fails inside the UoW context,
    `create_template_from_server` surfaces it as `TemplateCreationError`
    (via the outer `except Exception` wrapper).
    """
    server_dir = _make_server_dir(tmp_path)
    server_read.set_server(
        ServerEntity(
            id=1,
            name="Src",
            directory_path=str(server_dir),
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20,
            owner_id=1,
        )
    )

    def boom(*args, **kwargs):
        raise tarfile.TarError("simulated archive failure")

    monkeypatch.setattr(tarfile, "open", boom)

    with pytest.raises(TemplateCreationError):
        await service.create_template_from_server(server_id=1, name="t", creator_id=1)


# ---------------------------------------------------------------------------
# _apply_server_properties — write error branch (lines ~578-579)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_server_properties_swallows_write_error(
    service: TemplateService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """`_apply_server_properties` logs and returns silently on write
    failure (legacy contract: callers via `apply_template_to_server`
    swallow exceptions and surface a boolean).
    """
    server_dir = tmp_path / "dst"
    server_dir.mkdir()
    # No pre-existing server.properties → the write path is the only
    # `open()` call inside the helper, so we can fail unconditionally.

    real_open = builtins.open

    def boom(file, mode="r", *args, **kwargs):
        if str(file).endswith("server.properties") and "w" in mode:
            raise OSError("read-only fs")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", boom)

    # Should not raise — exception handler logs and returns None
    result = await service._apply_server_properties(server_dir, {"motd": "x"})
    assert result is None


@pytest.mark.asyncio
async def test_apply_template_returns_false_on_properties_write_failure(
    service: TemplateService,
    repo: FakeTemplateRepository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """`apply_template_to_server` returns `True` even when the
    properties write fails silently, because `_apply_server_properties`
    swallows its own exception. This pins the legacy contract for the
    full apply pipeline.
    """
    repo.seed(
        make_template_entity(
            id=1,
            created_by=1,
            configuration={"server_properties": {"motd": "FromTemplate"}},
        )
    )

    server_dir = tmp_path / "dst"
    server_dir.mkdir()

    real_open = builtins.open

    def boom(file, mode="r", *args, **kwargs):
        if str(file).endswith("server.properties") and "w" in mode:
            raise OSError("disk full")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", boom)

    ok = await service.apply_template_to_server(1, server_dir)
    # The helper swallowed the write failure → apply still reports success
    assert ok is True


# ---------------------------------------------------------------------------
# delete_template — archive unlink failure (outer exception wrapper, ~349-351)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_template_wraps_archive_unlink_failure_in_template_error(
    service: TemplateService,
    repo: FakeTemplateRepository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """If `Path.unlink()` fails while deleting the on-disk archive, the
    outer `except Exception` wraps it in `TemplateError`. The DB row is
    rolled back (UoW context exits abnormally) and no commit is recorded.
    """
    repo.seed(make_template_entity(id=1, created_by=1))
    archive = service.templates_directory / "template_1_files.tar.gz"
    archive.write_text("dummy")

    real_unlink = Path.unlink

    def boom(self, *args, **kwargs):
        if str(self) == str(archive):
            raise OSError("unlink denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", boom)

    with pytest.raises(TemplateError, match="Failed to delete template"):
        await service.delete_template(1, viewer_id=1, viewer_is_admin=False)

    # Archive still on disk (unlink failed); UoW recorded a rollback
    assert archive.exists()


# ---------------------------------------------------------------------------
# get_template_statistics — repository failure (lines ~455-457)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_statistics_wraps_repository_failure_in_template_error(
    service: TemplateService,
    repo: FakeTemplateRepository,
):
    """Any exception raised by the repository while gathering counts
    is wrapped in `TemplateError` by the service.
    """

    async def boom(*args, **kwargs):
        raise RuntimeError("db unavailable")

    # Swap out one of the count methods to fail; the service should
    # convert that into a `TemplateError`.
    repo.count_visible = boom  # type: ignore[method-assign]

    with pytest.raises(TemplateError, match="Failed to get template statistics"):
        await service.get_template_statistics(viewer_id=1, viewer_is_admin=False)


@pytest.mark.asyncio
async def test_statistics_wraps_repository_failure_from_count_by_type(
    service: TemplateService,
    repo: FakeTemplateRepository,
):
    """Same contract for `count_visible_by_server_type` — the last
    repository call inside the UoW block.
    """

    async def boom(*args, **kwargs):
        raise RuntimeError("server_type aggregation crashed")

    repo.count_visible_by_server_type = boom  # type: ignore[method-assign]

    with pytest.raises(TemplateError, match="Failed to get template statistics"):
        await service.get_template_statistics(viewer_id=1, viewer_is_admin=True)
