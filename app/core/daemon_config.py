"""
Daemon process configuration and validation
Handles configuration settings for daemon process creation and management
"""

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class DaemonMode(str, Enum):
    """Daemon process creation modes"""

    DOUBLE_FORK = "double_fork"
    SUBPROCESS_DAEMON = "subprocess_daemon"
    PROCESS_GROUP = "process_group"


class LogLevel(str, Enum):
    """Logging levels for daemon processes"""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class DaemonProcessLimits:
    """Resource limits for daemon processes"""

    max_memory_mb: int = 2048
    max_cpu_percent: float = 80.0
    max_open_files: int = 1024
    max_processes: int = 10
    timeout_seconds: int = 300


class DaemonConfig(BaseModel):
    """Configuration for daemon process creation and management"""

    # Process creation settings
    daemon_mode: DaemonMode = Field(
        default=DaemonMode.DOUBLE_FORK, description="Method for creating daemon processes"
    )

    enable_process_persistence: bool = Field(
        default=True, description="Enable PID file creation and process restoration"
    )

    pid_file_directory: Optional[Path] = Field(
        default=None, description="Directory for PID files (defaults to server directory)"
    )

    # Process monitoring settings
    enable_process_monitoring: bool = Field(
        default=True, description="Enable continuous process health monitoring"
    )

    monitoring_interval_seconds: int = Field(
        default=5, ge=1, le=60, description="Interval between process health checks"
    )

    process_startup_timeout_seconds: int = Field(
        default=30, ge=5, le=300, description="Timeout for process startup verification"
    )

    # Resource management
    resource_limits: DaemonProcessLimits = Field(
        default_factory=DaemonProcessLimits,
        description="Resource limits for daemon processes",
    )

    # Logging configuration
    log_level: LogLevel = Field(
        default=LogLevel.INFO, description="Logging level for daemon operations"
    )

    enable_daemon_logs: bool = Field(
        default=True, description="Enable logging for daemon process operations"
    )

    log_rotation_size_mb: int = Field(
        default=100, ge=1, le=1000, description="Log file rotation size in MB"
    )

    # Security settings
    enable_process_isolation: bool = Field(
        default=True, description="Enable process isolation verification"
    )

    verify_detachment: bool = Field(
        default=True, description="Verify proper daemon detachment"
    )

    secure_environment: bool = Field(
        default=True, description="Use secure environment variables"
    )

    # RCON integration settings
    enable_rcon_integration: bool = Field(
        default=True, description="Enable RCON for real-time commands"
    )

    rcon_timeout_seconds: int = Field(
        default=10, ge=1, le=60, description="RCON connection timeout"
    )

    rcon_retry_attempts: int = Field(
        default=3, ge=1, le=10, description="Number of RCON retry attempts"
    )

    # Process recovery settings
    enable_auto_recovery: bool = Field(
        default=True, description="Enable automatic process recovery on startup"
    )

    recovery_timeout_seconds: int = Field(
        default=60, ge=10, le=600, description="Timeout for recovery operations"
    )

    max_recovery_attempts: int = Field(
        default=3, ge=1, le=10, description="Maximum recovery attempts per process"
    )

    @validator("pid_file_directory")
    def validate_pid_directory(cls, v):
        """Validate PID file directory"""
        if v is not None:
            if not isinstance(v, Path):
                v = Path(v)

            # Check if directory exists or can be created
            try:
                v.mkdir(parents=True, exist_ok=True)
                if not v.is_dir():
                    raise ValueError(f"PID directory path is not a directory: {v}")
                if not os.access(v, os.W_OK):
                    raise ValueError(f"PID directory is not writable: {v}")
            except (OSError, PermissionError) as e:
                raise ValueError(f"Cannot access PID directory {v}: {e}")

        return v

    @validator("monitoring_interval_seconds")
    def validate_monitoring_interval(cls, v):
        """Validate monitoring interval"""
        if v <= 0:
            raise ValueError("Monitoring interval must be positive")
        if v > 300:  # 5 minutes max
            raise ValueError("Monitoring interval too long (max 300 seconds)")
        return v

    @validator("resource_limits")
    def validate_resource_limits(cls, v):
        """Validate resource limits"""
        if v.max_memory_mb <= 0:
            raise ValueError("Max memory must be positive")
        if v.max_memory_mb > 32768:  # 32GB max
            raise ValueError("Max memory too high (max 32768 MB)")

        if not 0 < v.max_cpu_percent <= 100:
            raise ValueError("CPU percent must be between 0 and 100")

        if v.max_open_files < 64:
            raise ValueError("Max open files too low (min 64)")
        if v.max_open_files > 65536:
            raise ValueError("Max open files too high (max 65536)")

        return v

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        return {
            "daemon_mode": self.daemon_mode.value,
            "enable_process_persistence": self.enable_process_persistence,
            "pid_file_directory": (
                str(self.pid_file_directory) if self.pid_file_directory else None
            ),
            "enable_process_monitoring": self.enable_process_monitoring,
            "monitoring_interval_seconds": self.monitoring_interval_seconds,
            "process_startup_timeout_seconds": self.process_startup_timeout_seconds,
            "resource_limits": {
                "max_memory_mb": self.resource_limits.max_memory_mb,
                "max_cpu_percent": self.resource_limits.max_cpu_percent,
                "max_open_files": self.resource_limits.max_open_files,
                "max_processes": self.resource_limits.max_processes,
                "timeout_seconds": self.resource_limits.timeout_seconds,
            },
            "log_level": self.log_level.value,
            "enable_daemon_logs": self.enable_daemon_logs,
            "log_rotation_size_mb": self.log_rotation_size_mb,
            "enable_process_isolation": self.enable_process_isolation,
            "verify_detachment": self.verify_detachment,
            "secure_environment": self.secure_environment,
            "enable_rcon_integration": self.enable_rcon_integration,
            "rcon_timeout_seconds": self.rcon_timeout_seconds,
            "rcon_retry_attempts": self.rcon_retry_attempts,
            "enable_auto_recovery": self.enable_auto_recovery,
            "recovery_timeout_seconds": self.recovery_timeout_seconds,
            "max_recovery_attempts": self.max_recovery_attempts,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DaemonConfig":
        """Create configuration from dictionary"""
        # Handle resource limits
        if "resource_limits" in data and isinstance(data["resource_limits"], dict):
            data["resource_limits"] = DaemonProcessLimits(**data["resource_limits"])

        return cls(**data)

    @classmethod
    def from_environment(cls) -> "DaemonConfig":
        """Create configuration from environment variables"""

        config_data = {}

        # Map environment variables to configuration
        env_mapping = {
            "DAEMON_MODE": "daemon_mode",
            "DAEMON_ENABLE_PERSISTENCE": "enable_process_persistence",
            "DAEMON_PID_DIRECTORY": "pid_file_directory",
            "DAEMON_ENABLE_MONITORING": "enable_process_monitoring",
            "DAEMON_MONITORING_INTERVAL": "monitoring_interval_seconds",
            "DAEMON_STARTUP_TIMEOUT": "process_startup_timeout_seconds",
            "DAEMON_LOG_LEVEL": "log_level",
            "DAEMON_ENABLE_LOGS": "enable_daemon_logs",
            "DAEMON_LOG_ROTATION_SIZE": "log_rotation_size_mb",
            "DAEMON_ENABLE_ISOLATION": "enable_process_isolation",
            "DAEMON_VERIFY_DETACHMENT": "verify_detachment",
            "DAEMON_SECURE_ENVIRONMENT": "secure_environment",
            "DAEMON_ENABLE_RCON": "enable_rcon_integration",
            "DAEMON_RCON_TIMEOUT": "rcon_timeout_seconds",
            "DAEMON_RCON_RETRY_ATTEMPTS": "rcon_retry_attempts",
            "DAEMON_ENABLE_AUTO_RECOVERY": "enable_auto_recovery",
            "DAEMON_RECOVERY_TIMEOUT": "recovery_timeout_seconds",
            "DAEMON_MAX_RECOVERY_ATTEMPTS": "max_recovery_attempts",
        }

        for env_var, config_key in env_mapping.items():
            value = os.getenv(env_var)
            if value is not None:
                # Convert string values to appropriate types
                if config_key in [
                    "enable_process_persistence",
                    "enable_process_monitoring",
                    "enable_daemon_logs",
                    "enable_process_isolation",
                    "verify_detachment",
                    "secure_environment",
                    "enable_rcon_integration",
                    "enable_auto_recovery",
                ]:
                    config_data[config_key] = value.lower() in ("true", "1", "yes", "on")
                elif config_key in [
                    "monitoring_interval_seconds",
                    "process_startup_timeout_seconds",
                    "log_rotation_size_mb",
                    "rcon_timeout_seconds",
                    "rcon_retry_attempts",
                    "recovery_timeout_seconds",
                    "max_recovery_attempts",
                ]:
                    config_data[config_key] = int(value)
                elif config_key == "pid_file_directory":
                    config_data[config_key] = Path(value)
                else:
                    config_data[config_key] = value

        # Handle resource limits from environment
        resource_limits = {}
        resource_env_mapping = {
            "DAEMON_MAX_MEMORY_MB": "max_memory_mb",
            "DAEMON_MAX_CPU_PERCENT": "max_cpu_percent",
            "DAEMON_MAX_OPEN_FILES": "max_open_files",
            "DAEMON_MAX_PROCESSES": "max_processes",
            "DAEMON_TIMEOUT_SECONDS": "timeout_seconds",
        }

        for env_var, limit_key in resource_env_mapping.items():
            value = os.getenv(env_var)
            if value is not None:
                if limit_key == "max_cpu_percent":
                    resource_limits[limit_key] = float(value)
                else:
                    resource_limits[limit_key] = int(value)

        if resource_limits:
            config_data["resource_limits"] = DaemonProcessLimits(**resource_limits)

        return cls(**config_data)

    def validate_configuration(self) -> List[str]:
        """Validate the configuration and return any errors"""
        errors = []

        # Validate combinations of settings
        if not self.enable_process_persistence and self.enable_auto_recovery:
            errors.append("Auto recovery requires process persistence to be enabled")

        if not self.enable_process_monitoring and self.enable_auto_recovery:
            errors.append("Auto recovery requires process monitoring to be enabled")

        if self.enable_rcon_integration and self.rcon_timeout_seconds <= 0:
            errors.append("RCON timeout must be positive when RCON is enabled")

        if self.process_startup_timeout_seconds < self.monitoring_interval_seconds:
            errors.append("Startup timeout should be longer than monitoring interval")

        # Validate resource limits consistency
        if self.resource_limits.timeout_seconds < self.process_startup_timeout_seconds:
            errors.append("Resource timeout should be longer than startup timeout")

        # Validate log settings
        if self.enable_daemon_logs and self.log_rotation_size_mb <= 0:
            errors.append("Log rotation size must be positive when logging is enabled")

        return errors


# Global daemon configuration instance
_daemon_config: Optional[DaemonConfig] = None


def get_daemon_config() -> DaemonConfig:
    """Get the global daemon configuration instance"""
    global _daemon_config
    if _daemon_config is None:
        _daemon_config = DaemonConfig.from_environment()
    return _daemon_config


def set_daemon_config(config: DaemonConfig) -> None:
    """Set the global daemon configuration instance"""
    global _daemon_config
    _daemon_config = config


def validate_daemon_configuration() -> List[str]:
    """Validate the current daemon configuration and return any errors"""
    config = get_daemon_config()
    return config.validate_configuration()


def reset_daemon_config() -> None:
    """Reset the global daemon configuration (for testing)"""
    global _daemon_config
    _daemon_config = None
