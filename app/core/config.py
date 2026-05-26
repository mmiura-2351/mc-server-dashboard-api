"""Application configuration (Issue #22 Phase 1).

Provides environment-specific configuration management on top of
``pydantic-settings``. Highlights:

* ``Environment`` enum (str-derived) classifies the running environment.
* ``.env`` files are loaded in a layered, env-aware order so per-environment
  overrides compose cleanly with the host's environment variables.
* Per-environment defaults (``_PER_ENV_DEFAULTS``) are injected *before*
  pydantic validation runs; explicit user values (env vars, ``.env`` entries,
  kwargs) always win.
* Hardening validators reject unsafe combinations in ``staging`` /
  ``production`` (sqlite DB, plaintext CORS, localhost origins).

See ``docs/CONFIGURATION.md`` for the full reference and load order.
"""

from __future__ import annotations

import functools
import os
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Runtime environment classifier.

    Subclassing ``str`` keeps backwards-compat with the previous
    ``ENVIRONMENT: str`` field — string equality (``settings.ENVIRONMENT ==
    "production"``) continues to work, JSON-serialisation yields the string
    value, and existing ``.env`` files with ``ENVIRONMENT=production`` still
    parse correctly.
    """

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"

    @classmethod
    def _missing_(cls, value: Any) -> "Environment":
        """Accept case-insensitive values (``"PRODUCTION"`` -> PRODUCTION)."""
        if isinstance(value, str):
            normalised = value.strip().lower()
            for member in cls:
                if member.value == normalised:
                    return member
        raise ValueError(
            f"Unknown ENVIRONMENT value: {value!r}. "
            f"Expected one of: {[m.value for m in cls]}"
        )


# Per-environment default overlay.
#
# Keys here are *not* applied when the user explicitly supplies a value via
# env var, ``.env`` file, or kwarg. They only fill in the gap between the
# class-level default and the host environment. See ``_apply_env_defaults``.
_PER_ENV_DEFAULTS: Dict[Environment, Dict[str, Any]] = {
    Environment.DEVELOPMENT: {
        "LOG_LEVEL": "INFO",
        "LOG_FORMAT": "text",
        "KEEP_SERVERS_ON_SHUTDOWN": True,
        "AUTO_SYNC_ON_STARTUP": True,
        "DATABASE_MAX_RETRIES": 3,
    },
    Environment.TESTING: {
        "LOG_LEVEL": "WARNING",
        "LOG_FORMAT": "text",
        "KEEP_SERVERS_ON_SHUTDOWN": False,
        "AUTO_SYNC_ON_STARTUP": False,
        "DATABASE_MAX_RETRIES": 1,
        # Drop bcrypt cost to the minimum (4) in tests to cut hash time
        # from ~150ms to ~0.5ms per call. Mirrors tests/helpers/security
        # which already pins rounds=4 for fixture-built hashes. Issue #79.
        "PASSWORD_BCRYPT_ROUNDS": 4,
    },
    Environment.STAGING: {
        "LOG_LEVEL": "INFO",
        "LOG_FORMAT": "json",
        "KEEP_SERVERS_ON_SHUTDOWN": True,
        "AUTO_SYNC_ON_STARTUP": True,
        "DATABASE_MAX_RETRIES": 3,
    },
    Environment.PRODUCTION: {
        "LOG_LEVEL": "INFO",
        "LOG_FORMAT": "json",
        "KEEP_SERVERS_ON_SHUTDOWN": True,
        "AUTO_SYNC_ON_STARTUP": True,
        "DATABASE_MAX_RETRIES": 5,
    },
}


def _resolve_active_environment_name() -> str:
    """Resolve the active environment name from ``os.environ`` at import time.

    Returns the lower-cased environment value (e.g. ``"production"``). If
    ``ENVIRONMENT`` is unset or invalid, falls back to ``"development"``.
    Invalid values are *not* raised here — the field validator on ``Settings``
    surfaces a clean error message at construction time instead.
    """
    raw = os.getenv("ENVIRONMENT", Environment.DEVELOPMENT.value)
    if not isinstance(raw, str):
        return Environment.DEVELOPMENT.value
    normalised = raw.strip().lower()
    if normalised not in {m.value for m in Environment}:
        return Environment.DEVELOPMENT.value
    return normalised


def _get_env_files() -> tuple[str, ...]:
    """Return the ordered ``.env`` file tuple for the active environment.

    Resolved once at class-definition time from ``os.environ['ENVIRONMENT']``.
    pydantic-settings treats later entries as *higher* precedence, so the
    returned tuple is ordered ``base -> per-env -> per-env.local``.
    ``os.environ`` still wins over all of these at instance construction.
    """
    name = _resolve_active_environment_name()
    return (".env", f".env.{name}", f".env.{name}.local")


class Settings(BaseSettings):
    """Application settings.

    Construction flow:

    1. pydantic-settings reads class defaults.
    2. ``_apply_env_defaults`` (``mode='before'``) injects per-environment
       defaults for keys not present in env vars / .env / kwargs.
    3. ``.env`` files are loaded (base → per-env → per-env.local).
    4. ``os.environ`` overrides everything above.
    5. Field & model validators run.
    """

    # ``env_file`` is resolved once at class-definition time from
    # ``os.environ['ENVIRONMENT']``. This avoids per-instance ``__init__``
    # mutation of pydantic-settings internals (which under xdist + CI can
    # interact with the settings sources pipeline and surface as
    # ``RecursionError``). The process-lifetime ``ENVIRONMENT`` value is
    # stable in practice, so a static resolution suffices.
    model_config = SettingsConfigDict(
        env_file=_get_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    DATABASE_URL: str

    # Server management configuration
    SERVER_LOG_QUEUE_SIZE: int = 500
    JAVA_CHECK_TIMEOUT: int = 5
    KEEP_SERVERS_ON_SHUTDOWN: bool = True  # Keep servers running when API shuts down
    AUTO_SYNC_ON_STARTUP: bool = True  # Auto-detect and sync running servers on startup

    # Java configuration for multi-version support
    JAVA_DISCOVERY_PATHS: str = (
        ""  # Comma-separated paths to search for Java installations
    )
    JAVA_8_PATH: str = ""  # Direct path to Java 8 executable
    JAVA_16_PATH: str = ""  # Direct path to Java 16 executable
    JAVA_17_PATH: str = ""  # Direct path to Java 17 executable
    JAVA_21_PATH: str = ""  # Direct path to Java 21 executable

    # Database configuration
    DATABASE_MAX_RETRIES: int = 3
    DATABASE_RETRY_BACKOFF: float = 0.1
    DATABASE_BATCH_SIZE: int = 100

    # Database connection pool configuration (Issue #369)
    # These are passed to SQLAlchemy's create_engine(); pool_size and
    # max_overflow are only applied for non-SQLite backends (SQLite uses
    # a single-connection pool by default).
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True

    # File upload size cap (Issue #341). Enforced by the file upload
    # service via a streaming/chunked read so the entire payload never
    # lands in process memory before the limit is checked. Defaults to
    # 100 MiB; override via the `FILE_MAX_UPLOAD_BYTES` env var. Set to
    # 0 to disable enforcement (not recommended for production).
    FILE_MAX_UPLOAD_BYTES: int = 100 * 1024 * 1024  # 100 MiB

    # Backup directory housekeeping (Issue #284)
    BACKUPS_PENDING_RETENTION_HOURS: int = 24
    BACKUPS_FAILED_RETENTION_DAYS: int = 30
    BACKUPS_CLEANUP_INTERVAL_SECONDS: int = 3600

    # Health check configuration (Issue #21)
    HEALTH_CHECK_PER_COMPONENT_TIMEOUT_SECONDS: float = 2.0
    HEALTH_CHECK_FS_TIMEOUT_SECONDS: float = 1.0
    HEALTH_CHECK_GLOBAL_TIMEOUT_SECONDS: float = 5.0
    HEALTH_CHECK_CACHE_TTL_SECONDS: float = 2.0

    # CORS configuration
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://127.0.0.1:3000,https://127.0.0.1:3000"
    )

    # Environment classifier (Issue #22). Defaults to DEVELOPMENT so local
    # `Settings(SECRET_KEY=..., DATABASE_URL=...)` invocations behave the
    # same as before when ENVIRONMENT is unset.
    ENVIRONMENT: Environment = Environment.DEVELOPMENT

    # Structured logging (issue #24, Phase 1)
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "text"
    LOG_FILE: Optional[str] = None
    LOG_FILE_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MiB
    LOG_FILE_BACKUP_COUNT: int = 5
    SQLALCHEMY_LOG_LEVEL: str = "WARNING"

    # ------------------------------------------------------------------
    # Per-environment defaults overlay
    # ------------------------------------------------------------------

    @model_validator(mode="before")
    @classmethod
    def _apply_env_defaults(cls, data: Any) -> Any:
        """Inject ``_PER_ENV_DEFAULTS`` for keys not explicitly provided.

        Runs at ``mode='before'`` so the overlay supplies values *before*
        pydantic checks required fields. Explicit values (kwargs, .env,
        os.environ) always win because we only ``setdefault`` keys that are
        not already present in ``data``.
        """
        if not isinstance(data, dict):
            return data

        raw_env = data.get("ENVIRONMENT") or os.getenv(
            "ENVIRONMENT", Environment.DEVELOPMENT.value
        )
        try:
            env = raw_env if isinstance(raw_env, Environment) else Environment(raw_env)
        except ValueError:
            # Defer to the field validator which will produce a clean error.
            return data

        overlay = _PER_ENV_DEFAULTS.get(env, {})
        for key, value in overlay.items():
            data.setdefault(key, value)
        return data

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def _coerce_environment(cls, v: Any) -> Environment:
        """Accept str (case-insensitive) and Environment alike."""
        if isinstance(v, Environment):
            return v
        if v is None:
            return Environment.DEVELOPMENT
        return Environment(v)

    # Password policy (Issue #73 — see docs/SECURITY.md). Production
    # defaults follow OWASP ASVS L1 + NIST 800-63B guidance. The
    # `PASSWORD_*` overrides are honoured by
    # `app.users.application.password_policy.get_password_policy()`.
    PASSWORD_MIN_LENGTH: int = 12
    PASSWORD_MAX_LENGTH: int = 128
    PASSWORD_REQUIRE_COMPLEXITY: bool = True
    PASSWORD_CHECK_COMMON_LIST: bool = True
    PASSWORD_FORBID_USER_INFO: bool = True
    PASSWORD_FORBID_SIMPLE_PATTERNS: bool = True
    # ISO-8601 date marking the policy release; users whose
    # `password_set_at` is NULL or older are "grandfathered" and
    # receive a warning header on successful login until they rotate.
    PASSWORD_POLICY_RELEASE_DATE: str = "2026-05-23"

    # Brute-force protection (Issue #73). Sliding-window counts of
    # failed logins are stored in `login_attempts`; lockouts in
    # `account_lockouts`. Lockout duration grows exponentially up to
    # `BRUTE_FORCE_LOCKOUT_MAX_SECONDS`.
    BRUTE_FORCE_ENABLED: bool = True
    BRUTE_FORCE_USERNAME_THRESHOLD: int = 5
    BRUTE_FORCE_USERNAME_WINDOW_SECONDS: int = 900  # 15 min
    BRUTE_FORCE_LOCKOUT_BASE_SECONDS: int = 900  # 15 min
    BRUTE_FORCE_LOCKOUT_MAX_SECONDS: int = 86400  # 24 h
    BRUTE_FORCE_IP_THRESHOLD: int = 20
    # IP lockout is a pure sliding-window check (no durable lockout row),
    # so the per-IP "retry after" returned to the client is the residual
    # of `BRUTE_FORCE_IP_WINDOW_SECONDS`. We deliberately removed
    # `BRUTE_FORCE_IP_LOCKOUT_SECONDS` (PR #333 review): keeping two
    # independent knobs let `retry_after` lie when they diverged.
    BRUTE_FORCE_IP_WINDOW_SECONDS: int = 300  # 5 min
    # Artificial delay (milliseconds) added to *every* failed-auth
    # path so attackers cannot use response latency to enumerate
    # valid usernames or to detect lockout state.
    BRUTE_FORCE_DELAY_MS: int = 200

    # Bcrypt cost factor used by the production `pwd_context` in
    # `app.users.application.service`. The production default of 12
    # is the OWASP ASVS L1 minimum; the testing overlay drops this
    # to 4 (see `_PER_ENV_DEFAULTS`) to keep registration / login
    # tests fast — bcrypt time grows ~2x per round, so 12 -> 4 yields
    # an ~256x speedup per hash. Anything <4 is rejected by bcrypt
    # itself; anything >15 takes seconds per call and is impractical.
    PASSWORD_BCRYPT_ROUNDS: int = 12

    # Reverse-proxy trust (Issue #73 review). See docs/SECURITY.md.
    # When False (default) X-Forwarded-For / X-Real-IP are *ignored*
    # entirely; the brute-force tracker uses `request.client.host`
    # only. When True, XFF / X-Real-IP are honoured ONLY if the
    # immediate peer (`request.client.host`) is listed in
    # `TRUSTED_PROXIES`. This prevents an attacker from spoofing the
    # source IP via XFF to dodge per-IP lockout.
    TRUST_PROXY_HEADERS: bool = False
    # Comma-separated list of trusted proxy IPs (no CIDR). Example:
    # "10.0.0.1,127.0.0.1". Empty list + TRUST_PROXY_HEADERS=True
    # effectively disables XFF trust (safe-by-default).
    TRUSTED_PROXIES: str = ""

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Validate SECRET_KEY meets security requirements"""
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")

        # Check for weak values (including as prefixes)
        weak_values = ["your-secret-key", "secret", "default", "change-me"]
        for weak in weak_values:
            if v.startswith(weak):
                raise ValueError("SECRET_KEY cannot be a default or weak value")

        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate LOG_LEVEL is one of the standard logging levels."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}, got: {v!r}")
        return upper

    @field_validator("SQLALCHEMY_LOG_LEVEL")
    @classmethod
    def validate_sqlalchemy_log_level(cls, v: str) -> str:
        """Validate SQLALCHEMY_LOG_LEVEL is a recognised logging level."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(
                f"SQLALCHEMY_LOG_LEVEL must be one of {sorted(allowed)}, got: {v!r}"
            )
        return upper

    @field_validator("LOG_FILE_MAX_BYTES")
    @classmethod
    def validate_log_file_max_bytes(cls, v: int) -> int:
        """Validate LOG_FILE_MAX_BYTES is within reasonable bounds."""
        if v < 1024 or v > 1024 * 1024 * 1024:
            raise ValueError("LOG_FILE_MAX_BYTES must be between 1KiB and 1GiB")
        return v

    @field_validator("LOG_FILE_BACKUP_COUNT")
    @classmethod
    def validate_log_file_backup_count(cls, v: int) -> int:
        """Validate LOG_FILE_BACKUP_COUNT is within reasonable bounds."""
        if v < 0 or v > 100:
            raise ValueError("LOG_FILE_BACKUP_COUNT must be between 0 and 100")
        return v

    @field_validator("SERVER_LOG_QUEUE_SIZE")
    @classmethod
    def validate_queue_size(cls, v: int) -> int:
        """Validate SERVER_LOG_QUEUE_SIZE is within reasonable limits"""
        if v < 100 or v > 10000:
            raise ValueError("SERVER_LOG_QUEUE_SIZE must be between 100 and 10000")
        return v

    @field_validator("JAVA_CHECK_TIMEOUT")
    @classmethod
    def validate_java_timeout(cls, v: int) -> int:
        """Validate JAVA_CHECK_TIMEOUT is within reasonable limits"""
        if v < 1 or v > 60:
            raise ValueError("JAVA_CHECK_TIMEOUT must be between 1 and 60 seconds")
        return v

    @field_validator("DATABASE_MAX_RETRIES")
    @classmethod
    def validate_db_retries(cls, v: int) -> int:
        """Validate DATABASE_MAX_RETRIES is within reasonable limits"""
        if v < 1 or v > 10:
            raise ValueError("DATABASE_MAX_RETRIES must be between 1 and 10")
        return v

    @field_validator("DATABASE_RETRY_BACKOFF")
    @classmethod
    def validate_db_backoff(cls, v: float) -> float:
        """Validate DATABASE_RETRY_BACKOFF is within reasonable limits"""
        if v < 0.01 or v > 5.0:
            raise ValueError(
                "DATABASE_RETRY_BACKOFF must be between 0.01 and 5.0 seconds"
            )
        return v

    @field_validator("DATABASE_BATCH_SIZE")
    @classmethod
    def validate_db_batch_size(cls, v: int) -> int:
        """Validate DATABASE_BATCH_SIZE is within reasonable limits"""
        if v < 10 or v > 1000:
            raise ValueError("DATABASE_BATCH_SIZE must be between 10 and 1000")
        return v

    @field_validator("DB_POOL_SIZE")
    @classmethod
    def validate_db_pool_size(cls, v: int) -> int:
        """Validate DB_POOL_SIZE is within reasonable limits."""
        if v < 1 or v > 100:
            raise ValueError("DB_POOL_SIZE must be between 1 and 100")
        return v

    @field_validator("DB_MAX_OVERFLOW")
    @classmethod
    def validate_db_max_overflow(cls, v: int) -> int:
        """Validate DB_MAX_OVERFLOW is within reasonable limits."""
        if v < 0 or v > 100:
            raise ValueError("DB_MAX_OVERFLOW must be between 0 and 100")
        return v

    @field_validator("DB_POOL_RECYCLE")
    @classmethod
    def validate_db_pool_recycle(cls, v: int) -> int:
        """Validate DB_POOL_RECYCLE is within reasonable limits."""
        if v < -1 or v > 86400:
            raise ValueError("DB_POOL_RECYCLE must be between -1 and 86400 seconds")
        return v

    @field_validator("FILE_MAX_UPLOAD_BYTES")
    @classmethod
    def validate_file_max_upload_bytes(cls, v: int) -> int:
        """Validate FILE_MAX_UPLOAD_BYTES is within reasonable bounds.

        0 disables enforcement. Otherwise must be in [1 KiB, 10 GiB].
        """
        if v == 0:
            return v
        if v < 1024 or v > 10 * 1024 * 1024 * 1024:
            raise ValueError(
                "FILE_MAX_UPLOAD_BYTES must be 0 (disabled) or between 1KiB and 10GiB"
            )
        return v

    @field_validator("BACKUPS_PENDING_RETENTION_HOURS")
    @classmethod
    def validate_pending_retention(cls, v: int) -> int:
        """Validate BACKUPS_PENDING_RETENTION_HOURS is within sane bounds."""
        if v < 1 or v > 24 * 365:
            raise ValueError(
                "BACKUPS_PENDING_RETENTION_HOURS must be between 1 and 8760 hours"
            )
        return v

    @field_validator("BACKUPS_FAILED_RETENTION_DAYS")
    @classmethod
    def validate_failed_retention(cls, v: int) -> int:
        """Validate BACKUPS_FAILED_RETENTION_DAYS is within sane bounds."""
        if v < 1 or v > 3650:
            raise ValueError(
                "BACKUPS_FAILED_RETENTION_DAYS must be between 1 and 3650 days"
            )
        return v

    @field_validator("BACKUPS_CLEANUP_INTERVAL_SECONDS")
    @classmethod
    def validate_cleanup_interval(cls, v: int) -> int:
        """Validate BACKUPS_CLEANUP_INTERVAL_SECONDS is within sane bounds."""
        if v < 60 or v > 86400:
            raise ValueError(
                "BACKUPS_CLEANUP_INTERVAL_SECONDS must be between 60 and 86400 seconds"
            )
        return v

    @field_validator(
        "HEALTH_CHECK_PER_COMPONENT_TIMEOUT_SECONDS",
        "HEALTH_CHECK_FS_TIMEOUT_SECONDS",
        "HEALTH_CHECK_GLOBAL_TIMEOUT_SECONDS",
        "HEALTH_CHECK_CACHE_TTL_SECONDS",
    )
    @classmethod
    def validate_health_check_timings(cls, v: float) -> float:
        """All health-check timing knobs must be strictly positive and
        below a 60s ceiling (anything larger would defeat the point of
        a sub-second probe interval)."""
        if v <= 0 or v > 60:
            raise ValueError("health check timing settings must be in (0, 60] seconds")
        return v

    @field_validator("PASSWORD_MIN_LENGTH")
    @classmethod
    def validate_password_min_length(cls, v: int) -> int:
        # Bcrypt truncates beyond 72 bytes; the lower bound is the most
        # permissive that still satisfies NIST 800-63B "minimum 8".
        if v < 8 or v > 72:
            raise ValueError("PASSWORD_MIN_LENGTH must be between 8 and 72")
        return v

    @field_validator("PASSWORD_MAX_LENGTH")
    @classmethod
    def validate_password_max_length(cls, v: int) -> int:
        # Upper bound limits DoS via huge bcrypt inputs; the lower
        # bound keeps the policy meaningful relative to the minimum.
        if v < 32 or v > 1024:
            raise ValueError("PASSWORD_MAX_LENGTH must be between 32 and 1024")
        return v

    @field_validator("BRUTE_FORCE_USERNAME_THRESHOLD", "BRUTE_FORCE_IP_THRESHOLD")
    @classmethod
    def validate_brute_force_threshold(cls, v: int) -> int:
        if v < 1 or v > 1000:
            raise ValueError("brute-force threshold must be between 1 and 1000")
        return v

    @field_validator(
        "BRUTE_FORCE_USERNAME_WINDOW_SECONDS",
        "BRUTE_FORCE_IP_WINDOW_SECONDS",
    )
    @classmethod
    def validate_brute_force_window(cls, v: int) -> int:
        if v < 30 or v > 86400:
            raise ValueError("brute-force window must be between 30 and 86400 seconds")
        return v

    @field_validator(
        "BRUTE_FORCE_LOCKOUT_BASE_SECONDS",
        "BRUTE_FORCE_LOCKOUT_MAX_SECONDS",
    )
    @classmethod
    def validate_brute_force_lockout(cls, v: int) -> int:
        if v < 1 or v > 7 * 86400:
            raise ValueError(
                "brute-force lockout duration must be between 1 second and 7 days"
            )
        return v

    @field_validator("BRUTE_FORCE_DELAY_MS")
    @classmethod
    def validate_brute_force_delay(cls, v: int) -> int:
        if v < 0 or v > 5000:
            raise ValueError("BRUTE_FORCE_DELAY_MS must be between 0 and 5000 ms")
        return v

    @field_validator("PASSWORD_BCRYPT_ROUNDS")
    @classmethod
    def validate_password_bcrypt_rounds(cls, v: int) -> int:
        """Validate PASSWORD_BCRYPT_ROUNDS is within bcrypt's supported range.

        Lower bound 4 matches bcrypt's hard minimum (passlib refuses anything
        below 4). Upper bound 15 keeps per-hash latency under ~5s on commodity
        hardware; values above 15 are operationally impractical.
        """
        if not (4 <= v <= 15):
            raise ValueError("PASSWORD_BCRYPT_ROUNDS must be in [4, 15]")
        return v

    # ------------------------------------------------------------------
    # Cross-field / environment-aware validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_cors_for_production(self) -> "Settings":
        """Reject ``localhost`` / ``127.0.0.1`` in production & staging CORS."""
        if self.ENVIRONMENT in (Environment.PRODUCTION, Environment.STAGING):
            if "localhost" in self.CORS_ORIGINS or "127.0.0.1" in self.CORS_ORIGINS:
                raise ValueError(
                    "CORS_ORIGINS should not include localhost in production"
                )
        return self

    @model_validator(mode="after")
    def validate_log_level_for_production(self) -> "Settings":
        """Reject DEBUG-level logging in production environments.

        Verbose request/response logging at DEBUG level can leak sensitive
        data in production, so this combination is explicitly disallowed.
        """
        if self.ENVIRONMENT == Environment.PRODUCTION and self.LOG_LEVEL == "DEBUG":
            raise ValueError(
                "LOG_LEVEL=DEBUG is not allowed in production "
                "(set ENVIRONMENT=development or raise the level)"
            )
        return self

    @model_validator(mode="after")
    def validate_production_hardening(self) -> "Settings":
        """Hardening rules applied only to ``ENVIRONMENT=production``.

        * SQLite is forbidden as the operational database — it does not support
          concurrent writes safely under multi-worker deployments.
        * All ``CORS_ORIGINS`` entries must be ``https://`` (TLS-only).

        Staging picks up a *subset* of these rules in
        ``validate_staging_hardening`` below.
        """
        if self.ENVIRONMENT != Environment.PRODUCTION:
            return self

        # Reject only genuine sqlite URLs by matching the scheme prefix,
        # rather than a substring search. The previous ``"sqlite" in url``
        # check spuriously rejected legitimate URLs whose credentials or
        # host portion happened to contain the literal string ``sqlite``
        # (for example ``postgresql://user:passsqlite@host/db``).
        if self.DATABASE_URL.lower().startswith(("sqlite:", "sqlite+")):
            raise ValueError(
                "DATABASE_URL with sqlite is not allowed in production "
                "(use postgresql:// or mysql:// instead)"
            )

        for origin in self.cors_origins_list:
            if not origin.lower().startswith("https://"):
                raise ValueError(
                    "CORS_ORIGINS in production must use https:// only "
                    f"(got non-https entry: {origin!r})"
                )

        return self

    @model_validator(mode="after")
    def validate_staging_hardening(self) -> "Settings":
        """Hardening rules applied to ``ENVIRONMENT=staging``.

        Staging mirrors the TLS-only CORS rule from production so that
        pre-prod environments fail fast on the same misconfigurations,
        but allows sqlite for ergonomics.
        """
        if self.ENVIRONMENT != Environment.STAGING:
            return self

        for origin in self.cors_origins_list:
            if not origin.lower().startswith("https://"):
                raise ValueError(
                    "CORS_ORIGINS in staging must use https:// only "
                    f"(got non-https entry: {origin!r})"
                )

        return self

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @functools.cached_property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string"""
        if not self.CORS_ORIGINS:
            return []
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]

    @functools.cached_property
    def trusted_proxies_list(self) -> List[str]:
        """Parse TRUSTED_PROXIES from a comma-separated string.

        Returns an empty list if unset. Caller is responsible for
        gating on `TRUST_PROXY_HEADERS` before consulting this list.
        """
        if not self.TRUSTED_PROXIES:
            return []
        return [
            entry.strip() for entry in self.TRUSTED_PROXIES.split(",") if entry.strip()
        ]

    @property
    def is_development(self) -> bool:
        """Check if running in development environment"""
        return self.ENVIRONMENT == Environment.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def is_testing(self) -> bool:
        """Check if running in testing environment"""
        return self.ENVIRONMENT == Environment.TESTING

    @property
    def is_staging(self) -> bool:
        """Check if running in staging environment"""
        return self.ENVIRONMENT == Environment.STAGING

    @functools.cached_property
    def java_discovery_paths_list(self) -> List[str]:
        """Parse Java discovery paths from comma-separated string"""
        if not self.JAVA_DISCOVERY_PATHS:
            return []
        return [
            path.strip() for path in self.JAVA_DISCOVERY_PATHS.split(",") if path.strip()
        ]

    def get_java_path(self, major_version: int) -> Optional[str]:
        """Get configured Java path for specific major version"""
        java_paths = {
            8: self.JAVA_8_PATH,
            16: self.JAVA_16_PATH,
            17: self.JAVA_17_PATH,
            21: self.JAVA_21_PATH,
        }
        path = java_paths.get(major_version, "")
        return path if path else None


settings = Settings()
