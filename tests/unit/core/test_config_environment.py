"""Tests for Issue #22 Phase 1 environment-specific configuration.

Covers:

* ``Environment`` enum parsing (case-insensitive, unknown rejected).
* Per-environment defaults overlay (only applied to keys not explicitly set).
* ``.env`` / ``.env.{environment}`` / ``.env.{environment}.local`` /
  ``os.environ`` precedence.
* Production hardening (sqlite rejected, https-only CORS).
* Staging hardening (https-only CORS, localhost forbidden).
* Backwards compatibility (``settings.ENVIRONMENT == "production"`` still
  evaluates True because Environment subclasses str).
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from app.core.config import _PER_ENV_DEFAULTS, Environment, Settings

SECRET = "this-is-a-very-secure-secret-key-with-sufficient-length"


# ---------------------------------------------------------------------------
# Environment enum
# ---------------------------------------------------------------------------


class TestEnvironmentEnum:
    def test_string_equality_backcompat(self):
        assert Environment.PRODUCTION == "production"
        assert Environment.DEVELOPMENT == "development"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("development", Environment.DEVELOPMENT),
            ("DEVELOPMENT", Environment.DEVELOPMENT),
            ("Production", Environment.PRODUCTION),
            ("  staging  ", Environment.STAGING),
            ("testing", Environment.TESTING),
        ],
    )
    def test_case_insensitive_parse(self, raw, expected):
        assert Environment(raw) is expected

    def test_unknown_value_raises(self):
        with pytest.raises(ValueError):
            Environment("preproduction")


# ---------------------------------------------------------------------------
# Per-env overlay
# ---------------------------------------------------------------------------


class TestPerEnvDefaults:
    def test_testing_overlay_applied(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("KEEP_SERVERS_ON_SHUTDOWN", raising=False)
        monkeypatch.delenv("AUTO_SYNC_ON_STARTUP", raising=False)
        monkeypatch.delenv("DATABASE_MAX_RETRIES", raising=False)

        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="sqlite:///./test.db",
            ENVIRONMENT="testing",
        )
        overlay = _PER_ENV_DEFAULTS[Environment.TESTING]
        assert s.LOG_LEVEL == overlay["LOG_LEVEL"]
        assert s.LOG_FORMAT == overlay["LOG_FORMAT"]
        assert s.KEEP_SERVERS_ON_SHUTDOWN is overlay["KEEP_SERVERS_ON_SHUTDOWN"]
        assert s.AUTO_SYNC_ON_STARTUP is overlay["AUTO_SYNC_ON_STARTUP"]
        assert s.DATABASE_MAX_RETRIES == overlay["DATABASE_MAX_RETRIES"]

    def test_production_overlay_applied(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("LOG_FORMAT", raising=False)
        monkeypatch.delenv("DATABASE_MAX_RETRIES", raising=False)

        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="postgresql://user:pw@db/app",
            ENVIRONMENT="production",
            CORS_ORIGINS="https://app.example.com",
        )
        assert s.LOG_FORMAT == "json"
        assert s.DATABASE_MAX_RETRIES == 5

    def test_explicit_kwargs_win_over_overlay(self, monkeypatch):
        """User-supplied values must defeat the per-env default overlay."""
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="sqlite:///./test.db",
            ENVIRONMENT="testing",
            LOG_LEVEL="ERROR",  # explicit
            KEEP_SERVERS_ON_SHUTDOWN=True,  # explicit (overlay would set False)
        )
        assert s.LOG_LEVEL == "ERROR"
        assert s.KEEP_SERVERS_ON_SHUTDOWN is True

    def test_explicit_env_var_wins_over_overlay(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="sqlite:///./test.db",
            ENVIRONMENT="testing",
        )
        assert s.LOG_LEVEL == "ERROR"


# ---------------------------------------------------------------------------
# .env file precedence
# ---------------------------------------------------------------------------


class TestEnvFilePrecedence:
    def _write(self, p, content):
        p.write_text(content, encoding="utf-8")

    def test_layered_files(self, tmp_path, monkeypatch):
        """``.env`` < ``.env.{env}`` < ``.env.{env}.local`` < ``os.environ``."""
        self._write(
            tmp_path / ".env",
            f"SECRET_KEY={SECRET}\n"
            "DATABASE_URL=postgresql://base\n"
            "CORS_ORIGINS=https://base.example.com\n",
        )
        self._write(
            tmp_path / ".env.production",
            "DATABASE_URL=postgresql://prod\nCORS_ORIGINS=https://prod.example.com\n",
        )
        self._write(
            tmp_path / ".env.production.local",
            "DATABASE_URL=postgresql://prod-local\n",
        )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ENVIRONMENT", "production")
        # Clear any inherited overrides so the file precedence is observable.
        for var in (
            "SECRET_KEY",
            "DATABASE_URL",
            "CORS_ORIGINS",
            "LOG_LEVEL",
            "LOG_FORMAT",
        ):
            monkeypatch.delenv(var, raising=False)

        s = Settings()
        # .local wins for DATABASE_URL
        assert s.DATABASE_URL == "postgresql://prod-local"
        # per-env file wins for CORS_ORIGINS over base
        assert s.CORS_ORIGINS == "https://prod.example.com"
        # base supplied SECRET_KEY
        assert s.SECRET_KEY == SECRET

    def test_os_environ_beats_env_files(self, tmp_path, monkeypatch):
        self._write(
            tmp_path / ".env",
            f"SECRET_KEY={SECRET}\n"
            "DATABASE_URL=postgresql://from-file\n"
            "CORS_ORIGINS=https://file.example.com\n",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("DATABASE_URL", "postgresql://from-env")
        monkeypatch.setenv("CORS_ORIGINS", "https://env.example.com")

        s = Settings()
        assert s.DATABASE_URL == "postgresql://from-env"
        assert s.CORS_ORIGINS == "https://env.example.com"


# ---------------------------------------------------------------------------
# Production hardening
# ---------------------------------------------------------------------------


class TestProductionHardening:
    def test_sqlite_rejected(self, monkeypatch):
        with pytest.raises(ValidationError, match="sqlite"):
            Settings(
                SECRET_KEY=SECRET,
                DATABASE_URL="sqlite:///./test.db",
                ENVIRONMENT="production",
                CORS_ORIGINS="https://example.com",
            )

    def test_postgres_accepted(self):
        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="postgresql://user:pw@db/app",
            ENVIRONMENT="production",
            CORS_ORIGINS="https://example.com",
        )
        assert s.is_production

    @pytest.mark.parametrize(
        "origin",
        [
            "http://example.com",
            "https://example.com,http://api.example.com",
            "ftp://example.com",
        ],
    )
    def test_non_https_origins_rejected(self, origin):
        with pytest.raises(ValidationError, match="https://"):
            Settings(
                SECRET_KEY=SECRET,
                DATABASE_URL="postgresql://user:pw@db/app",
                ENVIRONMENT="production",
                CORS_ORIGINS=origin,
            )

    def test_localhost_rejected(self):
        with pytest.raises(ValidationError, match="localhost"):
            Settings(
                SECRET_KEY=SECRET,
                DATABASE_URL="postgresql://user:pw@db/app",
                ENVIRONMENT="production",
                CORS_ORIGINS="https://example.com,http://localhost:3000",
            )


# ---------------------------------------------------------------------------
# Staging hardening
# ---------------------------------------------------------------------------


class TestStagingHardening:
    def test_sqlite_allowed(self):
        """Staging is more permissive than production on the DB front."""
        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="sqlite:///./staging.db",
            ENVIRONMENT="staging",
            CORS_ORIGINS="https://staging.example.com",
        )
        assert s.is_staging

    def test_non_https_rejected(self):
        with pytest.raises(ValidationError, match="https://"):
            Settings(
                SECRET_KEY=SECRET,
                DATABASE_URL="sqlite:///./staging.db",
                ENVIRONMENT="staging",
                CORS_ORIGINS="http://staging.example.com",
            )

    def test_localhost_rejected(self):
        with pytest.raises(ValidationError, match="localhost"):
            Settings(
                SECRET_KEY=SECRET,
                DATABASE_URL="sqlite:///./staging.db",
                ENVIRONMENT="staging",
                CORS_ORIGINS="https://staging.example.com,http://localhost:3000",
            )


# ---------------------------------------------------------------------------
# Environment field parsing
# ---------------------------------------------------------------------------


class TestEnvironmentField:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("development", Environment.DEVELOPMENT),
            ("DEVELOPMENT", Environment.DEVELOPMENT),
            ("Production", Environment.PRODUCTION),
            ("staging", Environment.STAGING),
            ("testing", Environment.TESTING),
        ],
    )
    def test_accepts_case_insensitive(self, raw, expected):
        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL=(
                "postgresql://user:pw@db/app"
                if expected is Environment.PRODUCTION
                else "sqlite:///./x.db"
            ),
            ENVIRONMENT=raw,
            CORS_ORIGINS=(
                "https://example.com"
                if expected in (Environment.PRODUCTION, Environment.STAGING)
                else "http://localhost:3000"
            ),
        )
        assert s.ENVIRONMENT is expected
        # String comparison must still hold (backcompat).
        assert s.ENVIRONMENT == expected.value

    def test_unknown_value_rejected(self):
        with pytest.raises(ValidationError):
            Settings(
                SECRET_KEY=SECRET,
                DATABASE_URL="sqlite:///./x.db",
                ENVIRONMENT="preproduction",
            )


# ---------------------------------------------------------------------------
# Convenience predicates
# ---------------------------------------------------------------------------


class TestEnvironmentPredicates:
    def test_is_helpers(self):
        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="sqlite:///./x.db",
            ENVIRONMENT="testing",
        )
        assert s.is_testing
        assert not s.is_development
        assert not s.is_staging
        assert not s.is_production


# ---------------------------------------------------------------------------
# Sanity: development is the default when ENVIRONMENT is unset.
# ---------------------------------------------------------------------------


def test_environment_defaults_to_development(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    s = Settings(SECRET_KEY=SECRET, DATABASE_URL="sqlite:///./x.db")
    assert s.is_development
    assert s.ENVIRONMENT == "development"
    assert isinstance(s.ENVIRONMENT, Environment)
    # overlay defaults for dev preserved
    assert s.LOG_FORMAT == "text"
    assert s.KEEP_SERVERS_ON_SHUTDOWN is True


def test_environment_unused_var_is_ignored():
    """os.environ values not declared on Settings should be tolerated."""
    os.environ["TOTALLY_UNRELATED_VAR"] = "irrelevant"
    try:
        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="sqlite:///./x.db",
            ENVIRONMENT="development",
        )
        assert s.is_development
    finally:
        del os.environ["TOTALLY_UNRELATED_VAR"]
