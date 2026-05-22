"""Unit tests for `AuditQueryService` using `FakeAuditRepository`."""

from datetime import datetime, timedelta, timezone

import pytest

from app.audit.application.query_service import AuditQueryService
from app.audit.domain.entities import LogFilters
from tests.unit.audit.fakes import FakeAuditRepository


@pytest.fixture
def repo() -> FakeAuditRepository:
    return FakeAuditRepository()


@pytest.fixture
def service(repo: FakeAuditRepository) -> AuditQueryService:
    return AuditQueryService(repo)


@pytest.mark.asyncio
async def test_list_logs_returns_page_and_total(
    service: AuditQueryService, repo: FakeAuditRepository
) -> None:
    for i in range(7):
        repo.add(action=f"a{i}", resource_type="t", user_id=1)
    logs, total = await service.list_logs(LogFilters(), page=1, page_size=5)
    assert total == 7
    assert len(logs) == 5


@pytest.mark.asyncio
async def test_list_logs_pagination_offset(
    service: AuditQueryService, repo: FakeAuditRepository
) -> None:
    for i in range(10):
        repo.add(action=f"a{i}", resource_type="t", user_id=1)
    page2, total = await service.list_logs(LogFilters(), page=2, page_size=3)
    assert total == 10
    assert len(page2) == 3
    # Sorted by created_at desc — fakes assign monotonic timestamps,
    # so page 2 (offset 3) should not overlap page 1 (offset 0).
    first_three, _ = await service.list_logs(LogFilters(), page=1, page_size=3)
    page2_ids = {e.id for e in page2}
    first_three_ids = {e.id for e in first_three}
    assert page2_ids.isdisjoint(first_three_ids)


@pytest.mark.asyncio
async def test_list_logs_filter_by_user(
    service: AuditQueryService, repo: FakeAuditRepository
) -> None:
    repo.add(action="x", resource_type="t", user_id=1)
    repo.add(action="x", resource_type="t", user_id=2)
    repo.add(action="x", resource_type="t", user_id=2)

    logs, total = await service.list_logs(LogFilters(user_id=2), page=1, page_size=10)
    assert total == 2
    assert all(log.user_id == 2 for log in logs)


@pytest.mark.asyncio
async def test_list_logs_filter_by_action_substring(
    service: AuditQueryService, repo: FakeAuditRepository
) -> None:
    repo.add(action="auth_login_success", resource_type="authentication")
    repo.add(action="auth_logout_success", resource_type="authentication")
    repo.add(action="server_start", resource_type="server")

    logs, total = await service.list_logs(LogFilters(action="auth"), page=1, page_size=10)
    assert total == 2
    assert all("auth" in log.action for log in logs)


@pytest.mark.asyncio
async def test_list_security_alerts_filters_by_severity(
    service: AuditQueryService, repo: FakeAuditRepository
) -> None:
    repo.add(
        action="security_x",
        resource_type="security",
        details={"severity": "critical"},
    )
    repo.add(
        action="security_y",
        resource_type="security",
        details={"severity": "low"},
    )
    repo.add(action="something_else", resource_type="server")

    alerts = await service.list_security_alerts("critical", limit=10)
    assert len(alerts) == 1
    assert alerts[0].action == "security_x"


@pytest.mark.asyncio
async def test_list_user_activity_scopes_to_user(
    service: AuditQueryService, repo: FakeAuditRepository
) -> None:
    repo.add(action="a", resource_type="t", user_id=1)
    repo.add(action="b", resource_type="t", user_id=1)
    repo.add(action="c", resource_type="t", user_id=2)

    activity = await service.list_user_activity(user_id=1, limit=10)
    assert len(activity) == 2
    assert all(log.user_id == 1 for log in activity)


@pytest.mark.asyncio
async def test_statistics_aggregates_correctly(
    service: AuditQueryService, repo: FakeAuditRepository
) -> None:
    now = datetime.now(timezone.utc)
    # Two recent (within 24h) auth events for user 1
    repo.add(action="auth_login", resource_type="authentication", user_id=1)
    repo.add(action="auth_login", resource_type="authentication", user_id=1)
    # One older (within 30d but outside 24h) security event
    repo.add(
        action="security_x",
        resource_type="security",
        user_id=2,
        details={"severity": "high"},
        created_at=now - timedelta(days=2),
    )
    # One ancient event (outside 30d) — must not appear in 30d aggregates
    repo.add(
        action="ancient",
        resource_type="server",
        user_id=1,
        created_at=now - timedelta(days=45),
    )

    stats = await service.get_statistics()

    assert stats.total_logs == 4
    assert stats.recent_logs_24h == 2
    # security event 2 days ago is inside the 7d window.
    assert stats.security_events_7d == 1

    # 30d aggregates: 3 entries inside (2 auth + 1 security), 1 outside
    most_active = dict(stats.most_active_users_30d)
    assert most_active.get(1) == 2  # 2 auth_login events
    assert most_active.get(2) == 1
