"""Unit tests for the ``app.health.adapters.*`` checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.health.adapters.database_check import DatabaseHealthCheck
from app.health.adapters.filesystem_check import FilesystemHealthCheck
from app.health.adapters.scheduler_check import _SchedulerCheck
from app.health.adapters.service_status_check import DatabaseIntegrationHealthCheck
from app.health.adapters.websocket_check import WebSocketHealthCheck
from app.health.domain.entities import HealthStatus


class TestDatabaseHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_engine(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        result = await DatabaseHealthCheck(engine).check()
        assert result.status is HealthStatus.HEALTHY
        assert result.critical is True
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_broken_engine_unhealthy(self) -> None:
        # Point at a non-existent driver to provoke a connection
        # failure inside ``Engine.connect()``.
        engine = create_engine("sqlite:////nonexistent/path/to/db.sqlite")

        # Force a real probe by monkeypatching ``connect`` to raise:
        def _boom(*args, **kwargs):
            raise RuntimeError("connection refused")

        engine.connect = _boom  # type: ignore[method-assign]
        result = await DatabaseHealthCheck(engine).check()
        assert result.status is HealthStatus.UNHEALTHY
        assert "connection refused" in (result.message or "")


class TestFilesystemHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_when_paths_writable(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        result = await FilesystemHealthCheck([a, b]).check()
        assert result.status is HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_missing_directory_unhealthy(self, tmp_path: Path) -> None:
        result = await FilesystemHealthCheck([tmp_path / "missing"]).check()
        assert result.status is HealthStatus.UNHEALTHY
        assert "missing" in (result.message or "")

    @pytest.mark.asyncio
    async def test_writability_probe_when_enabled(self, tmp_path: Path) -> None:
        result = await FilesystemHealthCheck([tmp_path], probe_writability=True).check()
        assert result.status is HealthStatus.HEALTHY


class TestSchedulerCheck:
    @pytest.mark.asyncio
    async def test_running_is_healthy(self) -> None:
        check = _SchedulerCheck(name="sched", is_running=lambda: True)
        result = await check.check()
        assert result.status is HealthStatus.HEALTHY
        assert result.critical is False

    @pytest.mark.asyncio
    async def test_not_running_is_degraded(self) -> None:
        check = _SchedulerCheck(name="sched", is_running=lambda: False)
        result = await check.check()
        assert result.status is HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_raising_is_unhealthy(self) -> None:
        def _boom() -> bool:
            raise RuntimeError("holder empty")

        check = _SchedulerCheck(name="sched", is_running=_boom)
        result = await check.check()
        assert result.status is HealthStatus.UNHEALTHY
        assert "holder empty" in (result.message or "")


class TestWebSocketHealthCheck:
    @pytest.mark.asyncio
    async def test_returns_status_for_monitoring_service(self, monkeypatch) -> None:
        class _FakeWS:
            def is_monitoring(self) -> bool:
                return True

        import app.websockets.application.service as svc_mod

        monkeypatch.setattr(svc_mod, "websocket_service", _FakeWS())
        result = await WebSocketHealthCheck().check()
        assert result.status is HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_reports_degraded_when_not_monitoring(self, monkeypatch) -> None:
        class _FakeWS:
            def is_monitoring(self) -> bool:
                return False

        import app.websockets.application.service as svc_mod

        monkeypatch.setattr(svc_mod, "websocket_service", _FakeWS())
        result = await WebSocketHealthCheck().check()
        assert result.status is HealthStatus.DEGRADED


class TestDatabaseIntegrationCheck:
    @pytest.mark.asyncio
    async def test_ready(self) -> None:
        check = DatabaseIntegrationHealthCheck(lambda: True)
        result = await check.check()
        assert result.status is HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_not_ready_is_degraded(self) -> None:
        check = DatabaseIntegrationHealthCheck(lambda: False)
        result = await check.check()
        assert result.status is HealthStatus.DEGRADED
