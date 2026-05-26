"""Validator tests for concurrency-related Settings fields (Issue #351)."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

_CONCURRENCY_KEYS = (
    "MAX_CONCURRENT_BACKUPS",
    "MAX_CONCURRENT_WEBSOCKETS",
    "FILE_IO_SEMAPHORE_LIMIT",
)


class TestConcurrencySettingsValidation:
    def _make_settings(self, **overrides):
        env = {
            "SECRET_KEY": "a" * 32,
            "DATABASE_URL": "sqlite:///./test.db",
            "ENVIRONMENT": "development",
        }
        env.update(overrides)

        # Clear stale concurrency env vars from prior tests
        for key in _CONCURRENCY_KEYS:
            os.environ.pop(key, None)

        for k, v in env.items():
            os.environ[k] = str(v)

        from app.core.config import Settings

        return Settings()

    def test_max_concurrent_backups_too_low(self):
        with pytest.raises(ValidationError, match="between 1 and 20"):
            self._make_settings(MAX_CONCURRENT_BACKUPS="0")

    def test_max_concurrent_backups_too_high(self):
        with pytest.raises(ValidationError, match="between 1 and 20"):
            self._make_settings(MAX_CONCURRENT_BACKUPS="21")

    def test_max_concurrent_backups_negative(self):
        with pytest.raises(ValidationError, match="between 1 and 20"):
            self._make_settings(MAX_CONCURRENT_BACKUPS="-1")

    def test_max_concurrent_websockets_too_low(self):
        with pytest.raises(ValidationError, match="between 1 and 10000"):
            self._make_settings(MAX_CONCURRENT_WEBSOCKETS="0")

    def test_max_concurrent_websockets_too_high(self):
        with pytest.raises(ValidationError, match="between 1 and 10000"):
            self._make_settings(MAX_CONCURRENT_WEBSOCKETS="10001")

    def test_file_io_semaphore_limit_too_low(self):
        with pytest.raises(ValidationError, match="between 1 and 100"):
            self._make_settings(FILE_IO_SEMAPHORE_LIMIT="0")

    def test_file_io_semaphore_limit_too_high(self):
        with pytest.raises(ValidationError, match="between 1 and 100"):
            self._make_settings(FILE_IO_SEMAPHORE_LIMIT="101")

    def test_backups_exceeds_file_io_limit(self):
        with pytest.raises(
            ValidationError,
            match="must not exceed FILE_IO_SEMAPHORE_LIMIT",
        ):
            self._make_settings(
                MAX_CONCURRENT_BACKUPS="5",
                FILE_IO_SEMAPHORE_LIMIT="3",
            )

    def test_valid_concurrency_settings(self):
        s = self._make_settings(
            MAX_CONCURRENT_BACKUPS="5",
            MAX_CONCURRENT_WEBSOCKETS="200",
            FILE_IO_SEMAPHORE_LIMIT="10",
        )
        assert s.MAX_CONCURRENT_BACKUPS == 5
        assert s.MAX_CONCURRENT_WEBSOCKETS == 200
        assert s.FILE_IO_SEMAPHORE_LIMIT == 10

    def test_backups_equal_to_file_io_limit_is_valid(self):
        s = self._make_settings(
            MAX_CONCURRENT_BACKUPS="10",
            FILE_IO_SEMAPHORE_LIMIT="10",
        )
        assert s.MAX_CONCURRENT_BACKUPS == 10
        assert s.FILE_IO_SEMAPHORE_LIMIT == 10
