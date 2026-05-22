"""Unit tests for `BackupSchedulerService.sweep_stale_pending_and_failed`.

Covers the Issue #284 housekeeping job that deletes stale artifacts
left behind by atomic-rename failure paths in `BackupService` (#228
PR 2e). Test strategy: create real files in a `tmp_path`-backed
`backups_directory`, manipulate their mtime to simulate age, run the
sweep, assert idempotency + retention boundaries + failure tolerance.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.backups.application.scheduler import BackupSchedulerService
from tests.unit.backups.fakes import FakeBackupsUnitOfWork, FakeServerReadPort

FROZEN_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_scheduler(
    backups_directory: Path,
    *,
    pending_retention_hours: int = 24,
    failed_retention_days: int = 30,
    cleanup_interval_seconds: int = 3600,
) -> BackupSchedulerService:
    return BackupSchedulerService(
        uow_factory=lambda: FakeBackupsUnitOfWork(),
        server_read_factory=lambda: FakeServerReadPort(),
        clock=lambda: FROZEN_NOW,
        backups_directory=backups_directory,
        pending_retention_hours=pending_retention_hours,
        failed_retention_days=failed_retention_days,
        cleanup_interval_seconds=cleanup_interval_seconds,
    )


def _write_with_age(path: Path, *, age_seconds: float) -> None:
    """Create `path` with content and set its mtime to `now - age_seconds`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    mtime = path.stat().st_mtime - age_seconds
    os.utime(path, (mtime, mtime))


class TestSweepPending:
    def test_no_pending_dir_is_noop(self, tmp_path):
        scheduler = _make_scheduler(tmp_path)
        result = scheduler.sweep_stale_pending_and_failed()
        assert result == {"pending_deleted": 0, "failed_deleted": 0}

    def test_deletes_pending_older_than_retention(self, tmp_path):
        scheduler = _make_scheduler(tmp_path, pending_retention_hours=24)
        stale = tmp_path / ".pending" / ".pending-stale.tar.gz"
        _write_with_age(stale, age_seconds=25 * 3600)

        result = scheduler.sweep_stale_pending_and_failed()
        assert result["pending_deleted"] == 1
        assert not stale.exists()

    def test_skips_pending_within_retention(self, tmp_path):
        scheduler = _make_scheduler(tmp_path, pending_retention_hours=24)
        fresh = tmp_path / ".pending" / ".pending-fresh.tar.gz"
        _write_with_age(fresh, age_seconds=1 * 3600)

        result = scheduler.sweep_stale_pending_and_failed()
        assert result["pending_deleted"] == 0
        assert fresh.exists()

    def test_ignores_non_tar_gz_files(self, tmp_path):
        scheduler = _make_scheduler(tmp_path, pending_retention_hours=24)
        weird = tmp_path / ".pending" / "stray.log"
        _write_with_age(weird, age_seconds=30 * 24 * 3600)

        result = scheduler.sweep_stale_pending_and_failed()
        assert result["pending_deleted"] == 0
        assert weird.exists()

    def test_idempotent_second_run_is_noop(self, tmp_path):
        scheduler = _make_scheduler(tmp_path, pending_retention_hours=24)
        stale = tmp_path / ".pending" / ".pending-stale.tar.gz"
        _write_with_age(stale, age_seconds=25 * 3600)
        scheduler.sweep_stale_pending_and_failed()
        # Second run with no remaining stale files.
        result = scheduler.sweep_stale_pending_and_failed()
        assert result == {"pending_deleted": 0, "failed_deleted": 0}


class TestSweepFailed:
    def test_deletes_failed_older_than_retention(self, tmp_path):
        scheduler = _make_scheduler(tmp_path, failed_retention_days=30)
        stale = tmp_path / ".failed" / "lost-uuid.tar.gz"
        _write_with_age(stale, age_seconds=31 * 24 * 3600)

        result = scheduler.sweep_stale_pending_and_failed()
        assert result["failed_deleted"] == 1
        assert not stale.exists()

    def test_skips_failed_within_retention(self, tmp_path):
        scheduler = _make_scheduler(tmp_path, failed_retention_days=30)
        fresh = tmp_path / ".failed" / "recent.tar.gz"
        _write_with_age(fresh, age_seconds=10 * 24 * 3600)

        result = scheduler.sweep_stale_pending_and_failed()
        assert result["failed_deleted"] == 0
        assert fresh.exists()


class TestSweepRobustness:
    def test_mixed_pending_and_failed(self, tmp_path):
        scheduler = _make_scheduler(
            tmp_path, pending_retention_hours=24, failed_retention_days=30
        )
        # stale pending + fresh pending
        _write_with_age(tmp_path / ".pending" / "a.tar.gz", age_seconds=48 * 3600)
        _write_with_age(tmp_path / ".pending" / "b.tar.gz", age_seconds=2 * 3600)
        # stale failed + fresh failed
        _write_with_age(tmp_path / ".failed" / "c.tar.gz", age_seconds=40 * 24 * 3600)
        _write_with_age(tmp_path / ".failed" / "d.tar.gz", age_seconds=5 * 24 * 3600)

        result = scheduler.sweep_stale_pending_and_failed()
        assert result == {"pending_deleted": 1, "failed_deleted": 1}
        assert (tmp_path / ".pending" / "b.tar.gz").exists()
        assert (tmp_path / ".failed" / "d.tar.gz").exists()

    def test_per_file_failure_does_not_abort_sweep(self, tmp_path, monkeypatch):
        """If `unlink` fails for one file, others should still be processed."""
        scheduler = _make_scheduler(tmp_path, pending_retention_hours=24)
        first = tmp_path / ".pending" / "a.tar.gz"
        second = tmp_path / ".pending" / "b.tar.gz"
        _write_with_age(first, age_seconds=48 * 3600)
        _write_with_age(second, age_seconds=48 * 3600)

        real_unlink = Path.unlink

        def _flaky_unlink(self, *args, **kwargs):
            if self.name == "a.tar.gz":
                raise PermissionError("denied")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _flaky_unlink)
        result = scheduler.sweep_stale_pending_and_failed()
        # one succeeded, one failed — the sweep continues.
        assert result["pending_deleted"] == 1
        assert first.exists()  # unlink failed
        assert not second.exists()  # unlink succeeded

    def test_retention_uses_settings_defaults(self, tmp_path, monkeypatch):
        """When constructor args are omitted, settings supply defaults."""
        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "BACKUPS_PENDING_RETENTION_HOURS", 1)
        monkeypatch.setattr(config_module.settings, "BACKUPS_FAILED_RETENTION_DAYS", 1)
        scheduler = BackupSchedulerService(
            uow_factory=lambda: FakeBackupsUnitOfWork(),
            server_read_factory=lambda: FakeServerReadPort(),
            clock=lambda: FROZEN_NOW,
            backups_directory=tmp_path,
        )
        _write_with_age(tmp_path / ".pending" / "a.tar.gz", age_seconds=2 * 3600)
        _write_with_age(tmp_path / ".failed" / "b.tar.gz", age_seconds=2 * 24 * 3600)
        result = scheduler.sweep_stale_pending_and_failed()
        assert result == {"pending_deleted": 1, "failed_deleted": 1}


class TestConfigValidators:
    """Issue #284 env-var validators in `Settings`."""

    def test_pending_retention_validator_rejects_zero(self):
        from app.core.config import Settings

        with pytest.raises(ValueError, match="BACKUPS_PENDING_RETENTION_HOURS"):
            Settings(
                SECRET_KEY="a" * 32,
                DATABASE_URL="sqlite:///./x.db",
                BACKUPS_PENDING_RETENTION_HOURS=0,
            )

    def test_failed_retention_validator_rejects_too_large(self):
        from app.core.config import Settings

        with pytest.raises(ValueError, match="BACKUPS_FAILED_RETENTION_DAYS"):
            Settings(
                SECRET_KEY="a" * 32,
                DATABASE_URL="sqlite:///./x.db",
                BACKUPS_FAILED_RETENTION_DAYS=100000,
            )

    def test_cleanup_interval_validator_rejects_too_small(self):
        from app.core.config import Settings

        with pytest.raises(ValueError, match="BACKUPS_CLEANUP_INTERVAL_SECONDS"):
            Settings(
                SECRET_KEY="a" * 32,
                DATABASE_URL="sqlite:///./x.db",
                BACKUPS_CLEANUP_INTERVAL_SECONDS=5,
            )

    def test_validators_accept_defaults(self):
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="a" * 32,
            DATABASE_URL="sqlite:///./x.db",
        )
        assert s.BACKUPS_PENDING_RETENTION_HOURS == 24
        assert s.BACKUPS_FAILED_RETENTION_DAYS == 30
        assert s.BACKUPS_CLEANUP_INTERVAL_SECONDS == 3600
