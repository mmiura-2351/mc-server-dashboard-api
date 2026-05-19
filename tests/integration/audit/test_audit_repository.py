"""Integration tests for `SqlAlchemyAuditRepository` and `SqlAlchemyAuditWriter`.

Uses the real worker-scoped SQLite test session. Confirms:

- The adapter converts ORM rows to `AuditLogEntity` (joined `user_email`
  included when the user row exists).
- The writer's direct-DB path persists rows and commits them on its
  own (no caller-side commit).
- The writer swallows failures rather than propagating.
- Statistics aggregate consistently with the underlying rows.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.audit.adapters.repository import (
    SqlAlchemyAuditRepository,
    SqlAlchemyAuditWriter,
)
from app.audit.domain.entities import AuditEventCommand, LogFilters
from app.audit.models import AuditLog
from app.users.models import Role, User


@pytest.fixture
def repository(db):
    return SqlAlchemyAuditRepository(db)


@pytest.fixture
def writer(db):
    return SqlAlchemyAuditWriter(db=db, tracker=None)


@pytest.fixture
def seeded_user(db):
    user = User(
        username="audit-target",
        email="audit-target@example.com",
        hashed_password="x",
        role=Role.user,
        is_active=True,
        is_approved=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_writer_persists_event(db, writer, seeded_user) -> None:
    writer.record(
        AuditEventCommand(
            action="server_start",
            resource_type="server",
            resource_id=42,
            user_id=seeded_user.id,
            details={"foo": "bar"},
            ip_address="10.0.0.1",
        )
    )
    # Writer commits on its own — fresh query sees the row.
    rows = db.query(AuditLog).filter(AuditLog.action == "server_start").all()
    assert len(rows) == 1
    assert rows[0].user_id == seeded_user.id
    assert rows[0].resource_id == 42
    assert rows[0].ip_address == "10.0.0.1"


@pytest.mark.asyncio
async def test_writer_swallows_errors(db, writer) -> None:
    """A bad command must not raise — audit is fire-and-forget."""

    class _Bomb:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    # Hand the writer something that explodes on attribute access; the
    # writer's try/except must keep this from propagating.
    writer._db = _Bomb()  # type: ignore[attr-defined]
    writer.record(
        AuditEventCommand(action="x", resource_type="t")
    )  # must not raise


@pytest.mark.asyncio
async def test_list_logs_returns_entities_with_user_email(
    db, writer, repository, seeded_user
) -> None:
    writer.record(
        AuditEventCommand(
            action="user_event",
            resource_type="server",
            user_id=seeded_user.id,
        )
    )
    logs = await repository.list_logs(
        LogFilters(action="user_event"), limit=10, offset=0
    )
    assert len(logs) == 1
    assert logs[0].user_id == seeded_user.id
    assert logs[0].user_email == seeded_user.email


@pytest.mark.asyncio
async def test_count_logs_matches_list(db, writer, repository) -> None:
    for i in range(3):
        writer.record(
            AuditEventCommand(
                action=f"countable_{i}", resource_type="t", user_id=99
            )
        )
    n = await repository.count_logs(LogFilters(user_id=99, action="countable"))
    assert n == 3


@pytest.mark.asyncio
async def test_list_user_activity(db, writer, repository, seeded_user) -> None:
    writer.record(
        AuditEventCommand(action="a", resource_type="t", user_id=seeded_user.id)
    )
    writer.record(
        AuditEventCommand(action="b", resource_type="t", user_id=seeded_user.id)
    )
    writer.record(
        AuditEventCommand(action="x", resource_type="t", user_id=seeded_user.id + 1)
    )

    rows = await repository.list_user_activity(seeded_user.id, limit=10)
    assert {r.action for r in rows} == {"a", "b"}


@pytest.mark.asyncio
async def test_security_alerts_filtered_by_resource_type(
    db, writer, repository
) -> None:
    writer.record(
        AuditEventCommand(
            action="security_x",
            resource_type="security",
            details={"severity": "critical"},
        )
    )
    writer.record(
        AuditEventCommand(action="other", resource_type="server")
    )
    alerts = await repository.list_security_alerts(severity=None, limit=10)
    assert all(a.resource_type == "security" for a in alerts)
    assert any(a.action == "security_x" for a in alerts)


@pytest.mark.asyncio
async def test_statistics_consistency(db, writer, repository) -> None:
    # Seed a few rows. Exact comparisons across the shared test
    # database would be fragile (other tests can leave residue
    # depending on isolation), so this test only checks the
    # invariants that must hold regardless of preceding state.
    now = datetime.now(timezone.utc)
    writer.record(
        AuditEventCommand(
            action="stats_seed_recent",
            resource_type="server",
            user_id=1234,
        )
    )

    stats = await repository.get_statistics()

    # The seeded recent action must show up in the 24h bucket.
    assert stats.recent_logs_24h >= 1
    # Total is monotonic in seeded rows.
    assert stats.total_logs >= stats.recent_logs_24h
    # All "most_active_users_30d" entries are (user_id, positive count).
    for uid, count in stats.most_active_users_30d:
        assert uid is not None
        assert count > 0
    # `now` is unused here but documents the temporal anchor.
    _ = now
