"""Unit tests for ``BusinessMetricsCollector`` (Issue #329).

These tests bypass the FastAPI stack entirely — the collector takes a
plain SQLAlchemy session + filesystem path and writes to module-level
Prometheus gauges. We assert on those gauge samples directly via the
``_value`` accessor exposed by the prometheus-client SDK.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.auth.models import AccountLockout
from app.backups.models import Backup
from app.core.datetime_utils import utcnow
from app.health.application.metrics_collector import (
    BusinessMetricsCollector,
    account_lockouts_active,
    backups_pending_total,
    servers_total,
)
from app.servers.domain.value_objects import BackupStatus, ServerStatus
from app.servers.models import Server


def _gauge_sample(gauge, **labels):
    """Return the current value for a labelled gauge sample."""
    if labels:
        return gauge.labels(**labels)._value.get()
    return gauge._value.get()


def _make_server(name: str, status: ServerStatus, *, owner_id: int) -> Server:
    return Server(
        name=name,
        directory_path=f"servers/{name}",
        port=25565,
        max_memory=1024,
        max_players=20,
        owner_id=owner_id,
        status=status,
        server_type="vanilla",
        minecraft_version="1.20.1",
    )


@pytest.fixture
def collector(db, tmp_path: Path) -> BusinessMetricsCollector:
    return BusinessMetricsCollector(db=db, backups_directory=tmp_path)


def test_collect_server_status_counts_emits_zero_for_every_status(
    collector: BusinessMetricsCollector,
) -> None:
    collector.collect()
    for status in ServerStatus:
        assert _gauge_sample(servers_total, status=status.value) == 0


def test_collect_server_status_counts_groups_by_status(
    collector: BusinessMetricsCollector,
    db,
    admin_user,
) -> None:
    db.add_all(
        [
            _make_server("running-a", ServerStatus.running, owner_id=admin_user.id),
            _make_server("running-b", ServerStatus.running, owner_id=admin_user.id),
            _make_server("stopped-a", ServerStatus.stopped, owner_id=admin_user.id),
        ]
    )
    db.commit()

    collector.collect()

    assert _gauge_sample(servers_total, status="running") == 2
    assert _gauge_sample(servers_total, status="stopped") == 1
    assert _gauge_sample(servers_total, status="error") == 0


def test_collect_pending_backups_combines_db_and_filesystem(
    collector: BusinessMetricsCollector,
    db,
    admin_user,
    tmp_path: Path,
) -> None:
    server = _make_server("backup-host", ServerStatus.stopped, owner_id=admin_user.id)
    db.add(server)
    db.flush()
    db.add(
        Backup(
            server_id=server.id,
            name="b1",
            file_path="/tmp/b1.tar.gz",
            file_size=1,
            status=BackupStatus.creating,
        )
    )
    db.add(
        Backup(
            server_id=server.id,
            name="b2-done",
            file_path="/tmp/b2.tar.gz",
            file_size=1,
            status=BackupStatus.completed,
        )
    )
    db.commit()

    # Two pending-on-disk archives that have not been promoted yet.
    pending_dir = tmp_path / ".pending"
    pending_dir.mkdir()
    (pending_dir / ".pending-aaa.tar.gz").touch()
    (pending_dir / ".pending-bbb.tar.gz").touch()
    # A non-tar file is ignored.
    (pending_dir / "README").touch()

    collector.collect()

    assert _gauge_sample(backups_pending_total) == 1 + 2  # one DB row + two FS files


def test_collect_active_lockouts(
    collector: BusinessMetricsCollector,
    db,
) -> None:
    now = utcnow()
    db.add_all(
        [
            AccountLockout(
                username="locked-1",
                locked_until=now + timedelta(minutes=5),
                lockout_count=1,
            ),
            AccountLockout(
                username="locked-2",
                locked_until=now + timedelta(minutes=10),
                lockout_count=1,
            ),
            AccountLockout(
                username="expired",
                locked_until=now - timedelta(minutes=1),
                lockout_count=1,
            ),
            AccountLockout(
                username="never",
                locked_until=None,
                lockout_count=0,
            ),
        ]
    )
    db.commit()

    collector.collect()

    assert _gauge_sample(account_lockouts_active) == 2
