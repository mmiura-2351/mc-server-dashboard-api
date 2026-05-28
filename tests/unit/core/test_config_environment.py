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

from app.core.config import (
    _PER_ENV_DEFAULTS,
    Environment,
    Settings,
    _get_env_files,
    _resolve_active_environment_name,
)

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
    """Verify the env_file tuple builder.

    ``env_file`` is resolved once at class-definition time of ``Settings``
    from ``os.environ['ENVIRONMENT']`` (see ``_get_env_files``). We test the
    helper directly because re-binding ``model_config.env_file`` per-instance
    interacted badly with pydantic-settings under CI xdist (``RecursionError``
    on a single worker). The layered ordering documented in
    ``docs/app/CONFIGURATION.md`` is unchanged in production code paths.
    """

    @pytest.mark.parametrize(
        "env_name,expected",
        [
            ("development", (".env", ".env.development", ".env.development.local")),
            ("testing", (".env", ".env.testing", ".env.testing.local")),
            ("staging", (".env", ".env.staging", ".env.staging.local")),
            ("production", (".env", ".env.production", ".env.production.local")),
        ],
    )
    def test_env_files_tuple_layering(self, env_name, expected, monkeypatch):
        """``_get_env_files`` returns ``base -> per-env -> per-env.local``."""
        monkeypatch.setenv("ENVIRONMENT", env_name)
        assert _get_env_files() == expected

    def test_env_files_defaults_to_development(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        assert _get_env_files() == (
            ".env",
            ".env.development",
            ".env.development.local",
        )

    def test_env_files_invalid_environment_falls_back_to_development(self, monkeypatch):
        """Invalid ENVIRONMENT must not crash file resolution — the field
        validator surfaces the bad value at ``Settings()`` construction."""
        monkeypatch.setenv("ENVIRONMENT", "preproduction")
        assert _get_env_files() == (
            ".env",
            ".env.development",
            ".env.development.local",
        )

    def test_resolve_active_environment_name_normalises_case(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "  PRODUCTION  ")
        assert _resolve_active_environment_name() == "production"

    def test_os_environ_beats_kwargs_via_env_var(self, monkeypatch):
        """``os.environ`` wins over class defaults — explicit kwargs still
        win over both. Verifies the precedence is honoured by
        pydantic-settings even with the static env_file layout."""
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="sqlite:///./test.db",
            ENVIRONMENT="development",
        )
        # os.environ overrides the dev overlay default of "INFO"
        assert s.LOG_LEVEL == "ERROR"

        # Explicit kwarg wins over os.environ
        s2 = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL="sqlite:///./test.db",
            ENVIRONMENT="development",
            LOG_LEVEL="WARNING",
        )
        assert s2.LOG_LEVEL == "WARNING"


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
        "url",
        [
            # Credentials happen to contain ``sqlite``.
            "postgresql://user:passsqlite@db/app",
            # Hostname / database name contains ``sqlite``.
            "postgresql://user:pw@sqlite-host.internal/app",
            "postgresql://user:pw@db/mysqlite_app",
            # MySQL with ``sqlite`` substring elsewhere.
            "mysql://sqliteadmin:pw@db/app",
        ],
    )
    def test_non_sqlite_url_with_sqlite_substring_accepted(self, url):
        """Production hardening must only reject genuine sqlite URLs.

        Previously the check did ``"sqlite" in url.lower()`` which spuriously
        rejected legitimate postgres / mysql URLs whose credentials or host
        portion happened to contain the literal ``sqlite``.
        """
        s = Settings(
            SECRET_KEY=SECRET,
            DATABASE_URL=url,
            ENVIRONMENT="production",
            CORS_ORIGINS="https://example.com",
        )
        assert s.is_production

    @pytest.mark.parametrize(
        "url",
        [
            "sqlite:///./test.db",
            "SQLite:///./test.db",
            "sqlite+pysqlite:///./test.db",
            "sqlite+aiosqlite:///./test.db",
        ],
    )
    def test_all_sqlite_schemes_rejected(self, url):
        """Both bare ``sqlite:`` and ``sqlite+driver:`` schemes are rejected."""
        with pytest.raises(ValidationError, match="sqlite"):
            Settings(
                SECRET_KEY=SECRET,
                DATABASE_URL=url,
                ENVIRONMENT="production",
                CORS_ORIGINS="https://example.com",
            )

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
