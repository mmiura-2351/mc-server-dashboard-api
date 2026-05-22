from typing import List, Optional

from pydantic import ConfigDict, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env")

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

    # Backup directory housekeeping (Issue #284)
    # Periodic sweep of `backups_directory/.pending/` and `.failed/`
    # artifacts left behind by atomic-rename failure paths (#228 PR 2e).
    BACKUPS_PENDING_RETENTION_HOURS: int = 24
    BACKUPS_FAILED_RETENTION_DAYS: int = 30
    # Interval (seconds) between sweep runs in the scheduler loop.
    BACKUPS_CLEANUP_INTERVAL_SECONDS: int = 3600

    # Health check configuration (Issue #21)
    # Per-component timeout: individual ``HealthCheckPort.check()``
    # invocations are bounded so one slow adapter cannot block the
    # whole probe.
    HEALTH_CHECK_PER_COMPONENT_TIMEOUT_SECONDS: float = 2.0
    # Filesystem probe budget (used by the FilesystemHealthCheck when
    # ``probe_writability=True``; the default os.access() path is
    # already nearly free).
    HEALTH_CHECK_FS_TIMEOUT_SECONDS: float = 1.0
    # Global guardrail: aggregates of the per-component runs are
    # bounded by this — defends against pathological misconfigurations
    # where every probe sits at the per-component timeout.
    HEALTH_CHECK_GLOBAL_TIMEOUT_SECONDS: float = 5.0
    # Short cache so k8s probing at ~1 Hz does not amplify into a
    # flood of database connections.
    HEALTH_CHECK_CACHE_TTL_SECONDS: float = 2.0

    # CORS configuration
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://127.0.0.1:3000,https://127.0.0.1:3000"
    )
    ENVIRONMENT: str = "development"  # development, production, testing

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

    @model_validator(mode="after")
    def validate_cors_for_production(self):
        """Validate CORS origins for production environment"""
        if self.ENVIRONMENT.lower() == "production":
            if "localhost" in self.CORS_ORIGINS or "127.0.0.1" in self.CORS_ORIGINS:
                raise ValueError(
                    "CORS_ORIGINS should not include localhost in production"
                )
        return self

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

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string"""
        if not self.CORS_ORIGINS:
            return []
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]

    @property
    def is_development(self) -> bool:
        """Check if running in development environment"""
        return self.ENVIRONMENT.lower() == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.ENVIRONMENT.lower() == "production"

    @property
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
