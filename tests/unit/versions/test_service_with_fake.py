"""Service-level unit tests using FakeUnitOfWork + FakeVersionRepository.

Demonstrates the target pattern for testing application-layer services:
inject an in-memory Fake of the domain Port instead of mocking SQLAlchemy
session chains. New tests should follow this style.
"""

import pytest

from app.servers.models import ServerType
from app.versions.application.service import VersionUpdateService
from app.versions.domain.entities import CreateVersionCommand
from tests.unit.versions.fakes import FakeUnitOfWork


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def service(uow: FakeUnitOfWork) -> VersionUpdateService:
    return VersionUpdateService(uow=uow)


class TestVersionUpdateServiceWithFake:
    @pytest.mark.asyncio
    async def test_get_all_supported_versions_empty(
        self, service: VersionUpdateService
    ) -> None:
        assert await service.get_all_supported_versions() == []

    @pytest.mark.asyncio
    async def test_get_supported_versions_after_seeding(
        self,
        service: VersionUpdateService,
        uow: FakeUnitOfWork,
    ) -> None:
        await uow.versions.create_version(
            CreateVersionCommand(
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
        uow: FakeUnitOfWork,
    ) -> None:
        for v in ("1.21.5", "1.21.6"):
            await uow.versions.create_version(
                CreateVersionCommand(
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

    @pytest.mark.asyncio
    async def test_query_methods_commit_nothing(
        self,
        service: VersionUpdateService,
        uow: FakeUnitOfWork,
    ) -> None:
        # Pure reads should not call commit; only mutations do.
        await service.get_all_supported_versions()
        await service.get_supported_versions(ServerType.vanilla)
        await service.get_version(ServerType.vanilla, "x")
        assert uow.committed == 0

    @pytest.mark.asyncio
    async def test_cleanup_old_versions_commits(
        self,
        service: VersionUpdateService,
        uow: FakeUnitOfWork,
    ) -> None:
        await service.cleanup_old_versions(days_old=30)
        assert uow.committed == 1
