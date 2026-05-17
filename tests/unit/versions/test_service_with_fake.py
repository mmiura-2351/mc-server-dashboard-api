"""Service-level unit tests using the in-memory FakeVersionRepository.

This file demonstrates the target pattern for testing application-layer
services: inject a Fake implementation of the domain Port instead of
mocking SQLAlchemy session chains. New tests should follow this style;
the older `test_service.py` will be migrated in a follow-up.
"""

import pytest

from app.servers.models import ServerType
from app.versions.adapters.repository import SqlAlchemyVersionRepository
from app.versions.application.service import VersionUpdateService
from app.versions.domain.ports import VersionRepository
from app.versions.schemas import MinecraftVersionCreate
from tests.unit.versions.fakes import FakeVersionRepository


class TestProtocolConformance:
    """`Fake` and `SqlAlchemy` adapters both satisfy the Port structurally."""

    def test_fake_repository_conforms_to_port(self) -> None:
        repo = FakeVersionRepository()
        assert isinstance(repo, VersionRepository)

    def test_sqlalchemy_repository_conforms_to_port(self) -> None:
        # Construction does not require a real session for the isinstance check.
        repo = SqlAlchemyVersionRepository(db=None)  # type: ignore[arg-type]
        assert isinstance(repo, VersionRepository)


class TestVersionUpdateServiceWithFake:
    @pytest.fixture
    def fake_repo(self) -> FakeVersionRepository:
        return FakeVersionRepository()

    @pytest.fixture
    def service(self, fake_repo: FakeVersionRepository) -> VersionUpdateService:
        return VersionUpdateService(repository=fake_repo)

    @pytest.mark.asyncio
    async def test_get_all_supported_versions_empty(
        self, service: VersionUpdateService
    ) -> None:
        assert await service.get_all_supported_versions() == []

    @pytest.mark.asyncio
    async def test_get_supported_versions_after_seeding(
        self,
        service: VersionUpdateService,
        fake_repo: FakeVersionRepository,
    ) -> None:
        await fake_repo.create_version(
            MinecraftVersionCreate(
                server_type=ServerType.vanilla,
                version="1.21.6",
                download_url="https://example.com/v.jar",
                is_stable=True,
            )
        )
        versions = await service.get_supported_versions(ServerType.vanilla)
        assert [v.version for v in versions] == ["1.21.6"]

    @pytest.mark.asyncio
    async def test_get_version_returns_none_when_missing(
        self, service: VersionUpdateService
    ) -> None:
        assert (
            await service.get_version(ServerType.vanilla, "1.99.0")
        ) is None

    @pytest.mark.asyncio
    async def test_get_version_stats_aggregates_by_type(
        self,
        service: VersionUpdateService,
        fake_repo: FakeVersionRepository,
    ) -> None:
        for v in ("1.21.5", "1.21.6"):
            await fake_repo.create_version(
                MinecraftVersionCreate(
                    server_type=ServerType.vanilla,
                    version=v,
                    download_url="https://example.com/v.jar",
                    is_stable=True,
                )
            )
        stats = await service.get_version_stats()
        assert stats.total_versions == 2
        assert stats.active_versions == 2
        assert stats.by_server_type["vanilla"]["active"] == 2
