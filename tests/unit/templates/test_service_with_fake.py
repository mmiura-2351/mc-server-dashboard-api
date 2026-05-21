"""Behavioural tests for `TemplateService` using in-memory fakes.

Exercises the use cases without a real DB or filesystem: each test
points `templates_directory` at `tmp_path` and lets the service write
archives there. The fakes act as the persistence layer.
"""

from pathlib import Path

import pytest

from app.servers.domain.entities import ServerEntity
from app.servers.models import ServerType
from app.templates.application.service import TemplateService
from app.templates.domain.exceptions import (
    TemplateAccessError,
    TemplateCreationError,
    TemplateError,
    TemplateNotFoundError,
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


def _make_server_dir(
    tmp_path: Path, name: str = "server1", with_properties: bool = True
) -> Path:
    server_dir = tmp_path / name
    server_dir.mkdir()
    if with_properties:
        (server_dir / "server.properties").write_text("motd=Test\n")
    return server_dir


# ----- create_template_from_server -----


@pytest.mark.asyncio
async def test_create_template_from_server_happy_path(
    service: TemplateService,
    server_read: FakeServerReadPort,
    uow: FakeTemplatesUnitOfWork,
    tmp_path: Path,
):
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
        )
    )

    entity = await service.create_template_from_server(
        server_id=1, name="from-server", creator_id=42, description="d"
    )

    assert entity.id is not None
    assert entity.name == "from-server"
    assert entity.minecraft_version == "1.20.1"
    assert entity.server_type == ServerType.vanilla
    # server.properties was extracted into configuration
    assert entity.configuration["server_properties"] == {"motd": "Test"}
    assert entity.configuration["metadata"]["original_server_id"] == 1
    # archive written to tmp_path/templates
    archive = service.templates_directory / f"template_{entity.id}_files.tar.gz"
    assert archive.exists()
    assert uow.committed >= 1


@pytest.mark.asyncio
async def test_create_template_from_server_server_not_found(
    service: TemplateService,
):
    with pytest.raises(TemplateNotFoundError):
        await service.create_template_from_server(
            server_id=999, name="x", creator_id=1
        )


@pytest.mark.asyncio
async def test_create_template_from_server_missing_directory(
    service: TemplateService,
    server_read: FakeServerReadPort,
    tmp_path: Path,
):
    server_read.set_server(
        ServerEntity(
            id=1,
            name="Ghost",
            directory_path=str(tmp_path / "nonexistent"),
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20,
        )
    )
    with pytest.raises(TemplateCreationError):
        await service.create_template_from_server(
            server_id=1, name="x", creator_id=1
        )


# ----- create_custom_template -----


@pytest.mark.asyncio
async def test_create_custom_template_happy_path(
    service: TemplateService, uow: FakeTemplatesUnitOfWork
):
    entity = await service.create_custom_template(
        name="custom",
        minecraft_version="1.20.1",
        server_type=ServerType.paper,
        configuration={"key": "value"},
        creator_id=7,
        description="my-desc",
        is_public=True,
    )

    assert entity.id is not None
    assert entity.is_public is True
    assert entity.created_by == 7
    assert entity.configuration == {"key": "value"}
    assert uow.committed >= 1


@pytest.mark.asyncio
async def test_create_custom_template_defaults_default_groups(
    service: TemplateService,
):
    entity = await service.create_custom_template(
        name="custom",
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        configuration={},
        creator_id=1,
    )
    assert entity.default_groups == {"op_groups": [], "whitelist_groups": []}


# ----- apply_template_to_server -----


@pytest.mark.asyncio
async def test_apply_template_to_server_with_archive(
    service: TemplateService,
    repo: FakeTemplateRepository,
    server_read: FakeServerReadPort,
    tmp_path: Path,
):
    server_dir = _make_server_dir(tmp_path, name="apply-dst")
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
        )
    )
    # Create a template via service so archive exists
    src_entity = await service.create_template_from_server(
        server_id=1, name="src", creator_id=1
    )

    # Now apply it back to a different dir
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    ok = await service.apply_template_to_server(src_entity.id, other_dir)
    assert ok is True
    assert (other_dir / "server.properties").exists()


@pytest.mark.asyncio
async def test_apply_template_returns_false_when_template_missing(
    service: TemplateService, tmp_path: Path
):
    server_dir = tmp_path / "dst"
    server_dir.mkdir()
    ok = await service.apply_template_to_server(999, server_dir)
    assert ok is False  # exception swallowed, matches legacy contract


# ----- get_template -----


@pytest.mark.asyncio
async def test_get_template_returns_none_when_missing(service: TemplateService):
    assert await service.get_template(99, viewer_id=1, viewer_is_admin=False) is None


@pytest.mark.asyncio
async def test_get_template_access_denied_for_private_non_owner(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(make_template_entity(id=1, created_by=42, is_public=False))
    with pytest.raises(TemplateAccessError):
        await service.get_template(1, viewer_id=999, viewer_is_admin=False)


@pytest.mark.asyncio
async def test_get_template_admin_sees_private(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(make_template_entity(id=1, created_by=42, is_public=False))
    got = await service.get_template(1, viewer_id=999, viewer_is_admin=True)
    assert got is not None
    assert got.id == 1


# ----- list_templates -----


@pytest.mark.asyncio
async def test_list_templates_non_admin_sees_only_visible(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(make_template_entity(id=1, created_by=1, is_public=False))
    repo.seed(make_template_entity(id=2, created_by=2, is_public=False))
    repo.seed(make_template_entity(id=3, created_by=2, is_public=True))

    page = await service.list_templates(
        viewer_id=1, viewer_is_admin=False
    )
    ids = {e.id for e in page.entities}
    # User 1 sees: their own (id=1) + public (id=3); NOT id=2
    assert ids == {1, 3}
    assert page.total == 2


@pytest.mark.asyncio
async def test_list_templates_admin_sees_all(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(make_template_entity(id=1, created_by=1, is_public=False))
    repo.seed(make_template_entity(id=2, created_by=2, is_public=False))
    page = await service.list_templates(
        viewer_id=999, viewer_is_admin=True
    )
    assert page.total == 2


@pytest.mark.asyncio
async def test_list_templates_filters_by_server_type(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(
        make_template_entity(id=1, created_by=1, server_type=ServerType.vanilla)
    )
    repo.seed(
        make_template_entity(id=2, created_by=1, server_type=ServerType.paper)
    )
    page = await service.list_templates(
        viewer_id=1, viewer_is_admin=False, server_type=ServerType.paper
    )
    assert [e.id for e in page.entities] == [2]


# ----- update_template -----


@pytest.mark.asyncio
async def test_update_returns_none_when_missing(service: TemplateService):
    assert (
        await service.update_template(999, viewer_id=1, viewer_is_admin=False) is None
    )


@pytest.mark.asyncio
async def test_update_denies_non_owner(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(make_template_entity(id=1, created_by=1))
    with pytest.raises(TemplateAccessError):
        await service.update_template(
            1, viewer_id=99, viewer_is_admin=False, name="new"
        )


@pytest.mark.asyncio
async def test_update_partial_fields(
    service: TemplateService,
    repo: FakeTemplateRepository,
    uow: FakeTemplatesUnitOfWork,
):
    repo.seed(make_template_entity(id=1, created_by=1, name="old", is_public=False))
    updated = await service.update_template(
        1, viewer_id=1, viewer_is_admin=False, name="new", is_public=True
    )
    assert updated is not None
    assert updated.name == "new"
    assert updated.is_public is True
    assert uow.committed >= 1


# ----- delete_template -----


@pytest.mark.asyncio
async def test_delete_returns_false_when_missing(service: TemplateService):
    ok = await service.delete_template(999, viewer_id=1, viewer_is_admin=False)
    assert ok is False


@pytest.mark.asyncio
async def test_delete_denied_for_non_owner(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(make_template_entity(id=1, created_by=1))
    with pytest.raises(TemplateAccessError):
        await service.delete_template(1, viewer_id=99, viewer_is_admin=False)


@pytest.mark.asyncio
async def test_delete_blocked_by_active_dependents(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(make_template_entity(id=1, created_by=1))
    repo.set_dependent_count(1, 2)
    with pytest.raises(TemplateError, match="2 servers"):
        await service.delete_template(1, viewer_id=1, viewer_is_admin=False)


@pytest.mark.asyncio
async def test_delete_happy_path_unlinks_archive(
    service: TemplateService,
    repo: FakeTemplateRepository,
    uow: FakeTemplatesUnitOfWork,
    tmp_path: Path,
):
    repo.seed(make_template_entity(id=1, created_by=1))
    # Pre-create the on-disk archive so the delete path exercises unlink()
    archive = service.templates_directory / "template_1_files.tar.gz"
    archive.write_text("dummy")

    ok = await service.delete_template(1, viewer_id=1, viewer_is_admin=False)
    assert ok is True
    assert not archive.exists()
    assert uow.committed >= 1


# ----- clone_template (shim parity; not exercised by the live router) -----


@pytest.mark.asyncio
async def test_clone_template_source_not_found(service: TemplateService):
    with pytest.raises(TemplateNotFoundError):
        await service.clone_template(
            999, name="x", viewer_id=1, viewer_is_admin=False
        )


@pytest.mark.asyncio
async def test_clone_template_access_denied(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(make_template_entity(id=1, created_by=42, is_public=False))
    with pytest.raises(TemplateAccessError):
        await service.clone_template(
            1, name="x", viewer_id=99, viewer_is_admin=False
        )


@pytest.mark.asyncio
async def test_clone_template_duplicate_name(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(make_template_entity(id=1, created_by=1, name="src", is_public=True))
    repo.seed(make_template_entity(id=2, created_by=99, name="dup"))
    with pytest.raises(TemplateError, match="already exists"):
        await service.clone_template(
            1, name="dup", viewer_id=99, viewer_is_admin=False
        )


@pytest.mark.asyncio
async def test_clone_template_happy_path(
    service: TemplateService,
    repo: FakeTemplateRepository,
    tmp_path: Path,
):
    repo.seed(
        make_template_entity(
            id=1, created_by=1, name="src", is_public=True,
            configuration={"k": "v"},
        )
    )
    # Pre-create an archive for the source template; clone should copy
    source_archive = service.templates_directory / "template_1_files.tar.gz"
    source_archive.write_text("archive")

    cloned = await service.clone_template(
        1, name="dst", viewer_id=99, viewer_is_admin=False
    )
    assert cloned.name == "dst"
    assert cloned.configuration == {"k": "v"}
    assert cloned.created_by == 99
    new_archive = (
        service.templates_directory / f"template_{cloned.id}_files.tar.gz"
    )
    assert new_archive.exists()


# ----- Router-level clone path (compose get + create_custom_template) -----


@pytest.mark.asyncio
async def test_router_style_clone_via_get_and_create_custom(
    service: TemplateService, repo: FakeTemplateRepository
):
    """The live router clones via `get_template + create_custom_template`,
    not via `TemplateService.clone_template`. Pin that this composition
    works end-to-end against the fakes."""
    repo.seed(
        make_template_entity(
            id=1, created_by=1, name="src", is_public=True,
            configuration={"k": "v"},
        )
    )

    original = await service.get_template(
        1, viewer_id=99, viewer_is_admin=False
    )
    assert original is not None

    cloned = await service.create_custom_template(
        name="dst",
        minecraft_version=original.minecraft_version,
        server_type=original.server_type,
        configuration=original.configuration,
        creator_id=99,
        description=f"Cloned from {original.name}",
        default_groups=original.default_groups,
        is_public=False,
    )
    assert cloned.name == "dst"
    assert cloned.created_by == 99


# ----- get_template_statistics -----


@pytest.mark.asyncio
async def test_statistics_for_non_admin_scoped_to_visible(
    service: TemplateService, repo: FakeTemplateRepository
):
    repo.seed(
        make_template_entity(
            id=1, created_by=1, is_public=False, server_type=ServerType.vanilla
        )
    )
    repo.seed(
        make_template_entity(
            id=2, created_by=2, is_public=False, server_type=ServerType.paper
        )
    )
    repo.seed(
        make_template_entity(
            id=3, created_by=2, is_public=True, server_type=ServerType.forge
        )
    )

    stats = await service.get_template_statistics(viewer_id=1, viewer_is_admin=False)

    # Visible to user 1: id=1 (own) and id=3 (public)
    assert stats["total_templates"] == 2
    assert stats["public_templates"] == 1
    assert stats["user_templates"] == 1
    # server_type_distribution keyed by ServerType.value, every type
    # initialised to 0 even when absent
    dist = stats["server_type_distribution"]
    assert dist[ServerType.vanilla.value] == 1
    assert dist[ServerType.forge.value] == 1
    assert dist[ServerType.paper.value] == 0


@pytest.mark.asyncio
async def test_count_owned_by_returns_only_my_templates_even_for_admin(
    service: TemplateService, repo: FakeTemplateRepository
):
    """`user_templates` reflects the caller's own templates only,
    regardless of admin status. Pins that `count_owned_by` is keyed by
    `viewer_id`, not by the visibility predicate."""
    repo.seed(make_template_entity(id=1, created_by=1))
    repo.seed(make_template_entity(id=2, created_by=2))
    repo.seed(make_template_entity(id=3, created_by=2))

    stats = await service.get_template_statistics(viewer_id=1, viewer_is_admin=True)
    # Admin can see all 3 but only owns 1
    assert stats["total_templates"] == 3
    assert stats["user_templates"] == 1
