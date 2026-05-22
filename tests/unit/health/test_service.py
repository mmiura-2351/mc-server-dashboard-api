"""Unit tests for ``HealthCheckService`` aggregation, timeout, caching."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.health.application.service import HealthCheckConfig, HealthCheckService
from app.health.domain.entities import ComponentHealth, HealthStatus, aggregate
from app.health.domain.ports import HealthCheckPort


class _StubCheck(HealthCheckPort):
    def __init__(
        self,
        *,
        name: str,
        critical: bool,
        status: HealthStatus,
        delay: float = 0.0,
        raises: BaseException | None = None,
        message: str | None = None,
    ) -> None:
        self.name = name
        self.critical = critical
        self._status = status
        self._delay = delay
        self._raises = raises
        self._message = message
        self.call_count = 0

    async def check(self) -> ComponentHealth:
        self.call_count += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        return ComponentHealth(
            name=self.name,
            status=self._status,
            critical=self.critical,
            message=self._message,
            checked_at=datetime.now(timezone.utc),
        )


def _config(**overrides: float) -> HealthCheckConfig:
    defaults = {
        "per_component_timeout_seconds": 0.5,
        "global_timeout_seconds": 1.5,
        "cache_ttl_seconds": 5.0,
    }
    defaults.update(overrides)
    return HealthCheckConfig(**defaults)  # type: ignore[arg-type]


class TestAggregate:
    def test_all_healthy(self) -> None:
        comps = [
            ComponentHealth(name="a", status=HealthStatus.HEALTHY, critical=True),
            ComponentHealth(name="b", status=HealthStatus.HEALTHY, critical=False),
        ]
        assert aggregate(comps) is HealthStatus.HEALTHY

    def test_non_critical_failure_degrades(self) -> None:
        comps = [
            ComponentHealth(name="a", status=HealthStatus.HEALTHY, critical=True),
            ComponentHealth(name="b", status=HealthStatus.UNHEALTHY, critical=False),
        ]
        assert aggregate(comps) is HealthStatus.DEGRADED

    def test_critical_failure_unhealthy(self) -> None:
        comps = [
            ComponentHealth(name="a", status=HealthStatus.UNHEALTHY, critical=True),
            ComponentHealth(name="b", status=HealthStatus.HEALTHY, critical=False),
        ]
        assert aggregate(comps) is HealthStatus.UNHEALTHY

    def test_degraded_alone_propagates(self) -> None:
        comps = [
            ComponentHealth(name="a", status=HealthStatus.DEGRADED, critical=False),
        ]
        assert aggregate(comps) is HealthStatus.DEGRADED


class TestLiveness:
    @pytest.mark.asyncio
    async def test_liveness_does_not_call_adapters(self) -> None:
        check = _StubCheck(name="db", critical=True, status=HealthStatus.HEALTHY)
        service = HealthCheckService([check], config=_config())
        result = service.liveness()
        assert result.status is HealthStatus.HEALTHY
        assert result.components == []
        assert check.call_count == 0


class TestReadinessAggregation:
    @pytest.mark.asyncio
    async def test_all_healthy(self) -> None:
        checks = [
            _StubCheck(name="db", critical=True, status=HealthStatus.HEALTHY),
            _StubCheck(name="fs", critical=True, status=HealthStatus.HEALTHY),
        ]
        service = HealthCheckService(checks, config=_config())
        result = await service.readiness()
        assert result.status is HealthStatus.HEALTHY
        assert result.is_ready is True
        assert {c.name for c in result.components} == {"db", "fs"}

    @pytest.mark.asyncio
    async def test_critical_failure_blocks_readiness(self) -> None:
        checks = [
            _StubCheck(name="db", critical=True, status=HealthStatus.UNHEALTHY),
            _StubCheck(name="ws", critical=False, status=HealthStatus.HEALTHY),
        ]
        service = HealthCheckService(checks, config=_config())
        result = await service.readiness()
        assert result.status is HealthStatus.UNHEALTHY
        assert result.is_ready is False

    @pytest.mark.asyncio
    async def test_non_critical_failure_stays_ready(self) -> None:
        checks = [
            _StubCheck(name="db", critical=True, status=HealthStatus.HEALTHY),
            _StubCheck(name="ws", critical=False, status=HealthStatus.UNHEALTHY),
        ]
        service = HealthCheckService(checks, config=_config())
        result = await service.readiness()
        assert result.status is HealthStatus.DEGRADED
        # Non-critical failure leaves readiness intact: the kubelet
        # should not pull traffic just because the backup scheduler is
        # asleep.
        assert result.is_ready is True


class TestPerComponentTimeout:
    @pytest.mark.asyncio
    async def test_slow_adapter_times_out_to_unhealthy(self) -> None:
        slow = _StubCheck(
            name="db",
            critical=True,
            status=HealthStatus.HEALTHY,
            delay=0.5,
        )
        fast = _StubCheck(name="fs", critical=False, status=HealthStatus.HEALTHY)
        service = HealthCheckService(
            [slow, fast],
            config=_config(per_component_timeout_seconds=0.05),
        )
        result = await service.readiness()
        by_name = {c.name: c for c in result.components}
        assert by_name["db"].status is HealthStatus.UNHEALTHY
        assert "timeout" in (by_name["db"].message or "")
        # Fast adapter should still return successfully.
        assert by_name["fs"].status is HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_raising_adapter_is_captured(self) -> None:
        boom = _StubCheck(
            name="fs",
            critical=True,
            status=HealthStatus.HEALTHY,
            raises=RuntimeError("disk on fire"),
        )
        service = HealthCheckService([boom], config=_config())
        result = await service.readiness()
        assert result.components[0].status is HealthStatus.UNHEALTHY
        assert "disk on fire" in (result.components[0].message or "")


class TestCache:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_check(self) -> None:
        check = _StubCheck(name="db", critical=True, status=HealthStatus.HEALTHY)
        service = HealthCheckService([check], config=_config(cache_ttl_seconds=10.0))
        await service.readiness()
        await service.readiness()
        await service.readiness()
        assert check.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_bypass_forces_rerun(self) -> None:
        check = _StubCheck(name="db", critical=True, status=HealthStatus.HEALTHY)
        service = HealthCheckService([check], config=_config(cache_ttl_seconds=10.0))
        await service.readiness()
        await service.readiness(use_cache=False)
        assert check.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_expires(self) -> None:
        check = _StubCheck(name="db", critical=True, status=HealthStatus.HEALTHY)
        service = HealthCheckService([check], config=_config(cache_ttl_seconds=0.01))
        await service.readiness()
        await asyncio.sleep(0.05)
        await service.readiness()
        assert check.call_count == 2
