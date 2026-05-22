"""Unit tests for the versions router.

Tests inject a service backed by `FakeUnitOfWork` via FastAPI's
`dependency_overrides` mechanism — no SQLAlchemy session, no
`MagicMock().query()` chains. This is the regulative pattern for #154's
follow-up sub-issues.
"""

from unittest.mock import patch

import pytest

from app.main import app
from app.servers.models import ServerType
from app.versions.api.dependencies import get_version_service
from app.versions.application.service import (
    VersionUpdateResult as ApplicationVersionUpdateResult,
)
from app.versions.application.service import (
    VersionUpdateService,
)
from app.versions.domain.entities import CreateVersionCommand
from tests.unit.versions.fakes import FakeUnitOfWork

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def override_service(fake_uow: FakeUnitOfWork):
    """Override the FastAPI DI binding for `get_version_service`."""
    service = VersionUpdateService(uow=fake_uow)
    app.dependency_overrides[get_version_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_version_service, None)


async def _seed(uow: FakeUnitOfWork, *commands: CreateVersionCommand) -> None:
    for c in commands:
        await uow.versions.create_version(c)


# ---------------------------------------------------------------------------
# /supported
# ---------------------------------------------------------------------------


class TestSupportedVersions:
    @pytest.mark.asyncio
    async def test_get_all(self, client, fake_uow, override_service):
        await _seed(
            fake_uow,
            CreateVersionCommand(
                server_type=ServerType.vanilla,
                version="1.21.6",
                download_url="https://example.com/v.jar",
                is_stable=True,
            ),
            CreateVersionCommand(
                server_type=ServerType.paper,
                version="1.21.6",
                download_url="https://example.com/p.jar",
                is_stable=True,
                build_number=123,
            ),
        )

        response = client.get("/api/v1/versions/supported")
        assert response.status_code == 200
        data = response.json()
        assert {row["server_type"] for row in data} == {"vanilla", "paper"}

    @pytest.mark.asyncio
    async def test_filter_by_server_type(self, client, fake_uow, override_service):
        await _seed(
            fake_uow,
            CreateVersionCommand(
                server_type=ServerType.vanilla,
                version="1.21.6",
                download_url="https://example.com/v.jar",
                is_stable=True,
            ),
            CreateVersionCommand(
                server_type=ServerType.paper,
                version="1.21.6",
                download_url="https://example.com/p.jar",
                is_stable=True,
            ),
        )

        response = client.get("/api/v1/versions/supported?server_type=vanilla")
        assert response.status_code == 200
        data = response.json()
        assert all(row["server_type"] == "vanilla" for row in data)
        assert len(data) == 1

    def test_database_error_returns_500(self, client, override_service):
        async def boom(*_args, **_kwargs):
            raise RuntimeError("DB exploded")

        override_service.get_all_supported_versions = boom  # type: ignore[method-assign]
        response = client.get("/api/v1/versions/supported")
        assert response.status_code == 500
        assert "Failed to retrieve versions" in response.json()["detail"]


# ---------------------------------------------------------------------------
# /{server_type}
# ---------------------------------------------------------------------------


class TestVersionsByServerType:
    @pytest.mark.asyncio
    async def test_returns_only_requested_type(self, client, fake_uow, override_service):
        await _seed(
            fake_uow,
            CreateVersionCommand(
                server_type=ServerType.paper,
                version="1.21.6",
                download_url="https://example.com/p.jar",
                is_stable=True,
            ),
        )
        response = client.get("/api/v1/versions/paper")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["server_type"] == "paper"


# ---------------------------------------------------------------------------
# /{server_type}/{version}
# ---------------------------------------------------------------------------


class TestSpecificVersion:
    @pytest.mark.asyncio
    async def test_found(self, client, fake_uow, override_service):
        await _seed(
            fake_uow,
            CreateVersionCommand(
                server_type=ServerType.vanilla,
                version="1.21.6",
                download_url="https://example.com/v.jar",
                is_stable=True,
            ),
        )
        response = client.get("/api/v1/versions/vanilla/1.21.6")
        assert response.status_code == 200
        assert response.json()["version"] == "1.21.6"

    def test_not_found(self, client, fake_uow, override_service):
        response = client.get("/api/v1/versions/forge/9.9.9")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


class TestVersionStats:
    @pytest.mark.asyncio
    async def test_aggregates(self, client, fake_uow, override_service):
        await _seed(
            fake_uow,
            CreateVersionCommand(
                server_type=ServerType.vanilla,
                version="1.21.6",
                download_url="https://example.com/v.jar",
                is_stable=True,
            ),
            CreateVersionCommand(
                server_type=ServerType.paper,
                version="1.21.6",
                download_url="https://example.com/p.jar",
                is_stable=True,
            ),
        )
        response = client.get("/api/v1/versions/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_versions"] == 2
        assert data["active_versions"] == 2
        assert set(data["by_server_type"]) == {"vanilla", "paper"}

    def test_error_returns_500(self, client, override_service):
        async def boom():
            raise RuntimeError("stats died")

        override_service.get_version_stats = boom  # type: ignore[method-assign]
        response = client.get("/api/v1/versions/stats")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# /update (admin only)
# ---------------------------------------------------------------------------


class TestTriggerVersionUpdate:
    def test_admin_triggers_update(self, client, admin_headers, override_service):
        async def fake_immediate_update(*, force_refresh: bool = False):
            return ApplicationVersionUpdateResult(
                success=True,
                message="ok",
                log_id=7,
                versions_added=1,
                versions_updated=0,
                versions_removed=0,
                execution_time_ms=42,
                errors=[],
            )

        with patch(
            "app.versions.api.router.version_update_scheduler.trigger_immediate_update",
            new=fake_immediate_update,
        ):
            response = client.post(
                "/api/v1/versions/update?force_refresh=true",
                headers=admin_headers,
            )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["log_id"] == 7

    def test_non_admin_forbidden(self, client, user_headers, override_service):
        response = client.post(
            "/api/v1/versions/update",
            headers=user_headers,
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# /scheduler/status (admin only)
# ---------------------------------------------------------------------------


class TestSchedulerStatus:
    def test_admin_reads_status(self, client, admin_headers, override_service):
        with patch(
            "app.versions.api.router.version_update_scheduler.get_status",
            return_value={
                "running": True,
                "update_interval_hours": 24,
                "last_successful_update": None,
                "next_update_time": None,
                "last_error": None,
                "retry_config": {"max_attempts": 3, "base_delay_seconds": 300},
            },
        ):
            response = client.get(
                "/api/v1/versions/scheduler/status",
                headers=admin_headers,
            )
        assert response.status_code == 200
        assert response.json()["running"] is True

    def test_non_admin_forbidden(self, client, user_headers, override_service):
        response = client.get(
            "/api/v1/versions/scheduler/status",
            headers=user_headers,
        )
        assert response.status_code == 403
