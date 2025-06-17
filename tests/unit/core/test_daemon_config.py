"""
Unit tests for daemon configuration validation
Tests configuration loading, validation, and error handling
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock

import pytest
from pydantic import ValidationError

from app.core.daemon_config import (
    DaemonConfig,
    DaemonMode,
    LogLevel,
    DaemonProcessLimits,
    get_daemon_config,
    set_daemon_config,
    validate_daemon_configuration,
    reset_daemon_config
)


class TestDaemonProcessLimits:
    """Test daemon process limits configuration"""
    
    def test_default_limits(self):
        """Test default resource limits"""
        limits = DaemonProcessLimits()
        
        assert limits.max_memory_mb == 2048
        assert limits.max_cpu_percent == 80.0
        assert limits.max_open_files == 1024
        assert limits.max_processes == 10
        assert limits.timeout_seconds == 300
    
    def test_custom_limits(self):
        """Test custom resource limits"""
        limits = DaemonProcessLimits(
            max_memory_mb=4096,
            max_cpu_percent=90.0,
            max_open_files=2048,
            max_processes=20,
            timeout_seconds=600
        )
        
        assert limits.max_memory_mb == 4096
        assert limits.max_cpu_percent == 90.0
        assert limits.max_open_files == 2048
        assert limits.max_processes == 20
        assert limits.timeout_seconds == 600


class TestDaemonConfig:
    """Test daemon configuration class"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = DaemonConfig()
        
        assert config.daemon_mode == DaemonMode.DOUBLE_FORK
        assert config.enable_process_persistence is True
        assert config.pid_file_directory is None
        assert config.enable_process_monitoring is True
        assert config.monitoring_interval_seconds == 5
        assert config.process_startup_timeout_seconds == 30
        assert config.log_level == LogLevel.INFO
        assert config.enable_daemon_logs is True
        assert config.log_rotation_size_mb == 100
        assert config.enable_process_isolation is True
        assert config.verify_detachment is True
        assert config.secure_environment is True
        assert config.enable_rcon_integration is True
        assert config.rcon_timeout_seconds == 10
        assert config.rcon_retry_attempts == 3
        assert config.enable_auto_recovery is True
        assert config.recovery_timeout_seconds == 60
        assert config.max_recovery_attempts == 3
    
    def test_custom_config(self):
        """Test custom configuration values"""
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_dir = Path(temp_dir) / "pids"
            
            config = DaemonConfig(
                daemon_mode=DaemonMode.SUBPROCESS_DAEMON,
                enable_process_persistence=False,
                pid_file_directory=pid_dir,
                monitoring_interval_seconds=10,
                log_level=LogLevel.DEBUG,
                enable_rcon_integration=False,
                max_recovery_attempts=5
            )
            
            assert config.daemon_mode == DaemonMode.SUBPROCESS_DAEMON
            assert config.enable_process_persistence is False
            assert config.pid_file_directory == pid_dir
            assert config.monitoring_interval_seconds == 10
            assert config.log_level == LogLevel.DEBUG
            assert config.enable_rcon_integration is False
            assert config.max_recovery_attempts == 5

    def test_pid_directory_validation_success(self):
        """Test successful PID directory validation"""
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_dir = Path(temp_dir) / "test_pids"
            
            config = DaemonConfig(pid_file_directory=pid_dir)
            
            assert config.pid_file_directory == pid_dir
            assert pid_dir.exists()
            assert pid_dir.is_dir()

    def test_pid_directory_validation_failure(self):
        """Test PID directory validation failure"""
        # Test with invalid directory (file instead of directory)
        with tempfile.NamedTemporaryFile() as temp_file:
            with pytest.raises(ValidationError) as exc_info:
                DaemonConfig(pid_file_directory=temp_file.name)
            
            assert "not a directory" in str(exc_info.value)

    def test_monitoring_interval_validation(self):
        """Test monitoring interval validation"""
        # Test valid intervals
        config = DaemonConfig(monitoring_interval_seconds=1)
        assert config.monitoring_interval_seconds == 1
        
        config = DaemonConfig(monitoring_interval_seconds=60)
        assert config.monitoring_interval_seconds == 60
        
        # Test invalid intervals
        with pytest.raises(ValidationError):
            DaemonConfig(monitoring_interval_seconds=0)
        
        with pytest.raises(ValidationError):
            DaemonConfig(monitoring_interval_seconds=-1)
        
        with pytest.raises(ValidationError):
            DaemonConfig(monitoring_interval_seconds=61)

    def test_resource_limits_validation(self):
        """Test resource limits validation"""
        # Test valid limits
        limits = DaemonProcessLimits(
            max_memory_mb=1024,
            max_cpu_percent=50.0,
            max_open_files=512,
            max_processes=5
        )
        config = DaemonConfig(resource_limits=limits)
        assert config.resource_limits.max_memory_mb == 1024
        
        # Test invalid memory limit
        with pytest.raises(ValidationError):
            DaemonConfig(resource_limits=DaemonProcessLimits(max_memory_mb=0))
        
        with pytest.raises(ValidationError):
            DaemonConfig(resource_limits=DaemonProcessLimits(max_memory_mb=40000))
        
        # Test invalid CPU percent
        with pytest.raises(ValidationError):
            DaemonConfig(resource_limits=DaemonProcessLimits(max_cpu_percent=0))
        
        with pytest.raises(ValidationError):
            DaemonConfig(resource_limits=DaemonProcessLimits(max_cpu_percent=101))
        
        # Test invalid file limits
        with pytest.raises(ValidationError):
            DaemonConfig(resource_limits=DaemonProcessLimits(max_open_files=32))
        
        with pytest.raises(ValidationError):
            DaemonConfig(resource_limits=DaemonProcessLimits(max_open_files=100000))

    def test_to_dict_conversion(self):
        """Test configuration conversion to dictionary"""
        config = DaemonConfig(
            daemon_mode=DaemonMode.PROCESS_GROUP,
            monitoring_interval_seconds=15,
            log_level=LogLevel.WARNING
        )
        
        result = config.to_dict()
        
        assert isinstance(result, dict)
        assert result['daemon_mode'] == 'process_group'
        assert result['monitoring_interval_seconds'] == 15
        assert result['log_level'] == 'warning'
        assert 'resource_limits' in result
        assert isinstance(result['resource_limits'], dict)

    def test_from_dict_conversion(self):
        """Test configuration creation from dictionary"""
        data = {
            'daemon_mode': 'subprocess_daemon',
            'monitoring_interval_seconds': 20,
            'log_level': 'error',
            'resource_limits': {
                'max_memory_mb': 4096,
                'max_cpu_percent': 75.0,
                'max_open_files': 2048,
                'max_processes': 15,
                'timeout_seconds': 500
            }
        }
        
        config = DaemonConfig.from_dict(data)
        
        assert config.daemon_mode == DaemonMode.SUBPROCESS_DAEMON
        assert config.monitoring_interval_seconds == 20
        assert config.log_level == LogLevel.ERROR
        assert config.resource_limits.max_memory_mb == 4096
        assert config.resource_limits.max_cpu_percent == 75.0

    def test_from_environment_conversion(self):
        """Test configuration creation from environment variables"""
        env_vars = {
            'DAEMON_MODE': 'process_group',
            'DAEMON_ENABLE_PERSISTENCE': 'false',
            'DAEMON_MONITORING_INTERVAL': '25',
            'DAEMON_LOG_LEVEL': 'debug',
            'DAEMON_ENABLE_RCON': 'false',
            'DAEMON_MAX_MEMORY_MB': '8192',
            'DAEMON_MAX_CPU_PERCENT': '95.0',
            'DAEMON_RCON_TIMEOUT': '15'
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            config = DaemonConfig.from_environment()
            
            assert config.daemon_mode == DaemonMode.PROCESS_GROUP
            assert config.enable_process_persistence is False
            assert config.monitoring_interval_seconds == 25
            assert config.log_level == LogLevel.DEBUG
            assert config.enable_rcon_integration is False
            assert config.resource_limits.max_memory_mb == 8192
            assert config.resource_limits.max_cpu_percent == 95.0
            assert config.rcon_timeout_seconds == 15

    def test_configuration_validation_success(self):
        """Test successful configuration validation"""
        config = DaemonConfig(
            enable_process_persistence=True,
            enable_process_monitoring=True,
            enable_auto_recovery=True,
            process_startup_timeout_seconds=60,
            monitoring_interval_seconds=10,
            resource_limits=DaemonProcessLimits(timeout_seconds=120)
        )
        
        errors = config.validate_configuration()
        assert len(errors) == 0

    def test_configuration_validation_failures(self):
        """Test configuration validation failures"""
        # Test auto recovery without persistence
        config = DaemonConfig(
            enable_process_persistence=False,
            enable_auto_recovery=True
        )
        errors = config.validate_configuration()
        assert len(errors) >= 1
        assert any("Auto recovery requires process persistence" in error for error in errors)
        
        # Test auto recovery without monitoring
        config = DaemonConfig(
            enable_process_monitoring=False,
            enable_auto_recovery=True
        )
        errors = config.validate_configuration()
        assert len(errors) >= 1
        assert any("Auto recovery requires process monitoring" in error for error in errors)
        
        # Test invalid timeout relationships
        config = DaemonConfig(
            process_startup_timeout_seconds=5,
            monitoring_interval_seconds=10
        )
        errors = config.validate_configuration()
        assert len(errors) >= 1
        assert any("Startup timeout should be longer" in error for error in errors)
        
        # Test RCON configuration inconsistency
        config = DaemonConfig(
            enable_rcon_integration=True,
            rcon_timeout_seconds=0
        )
        errors = config.validate_configuration()
        assert len(errors) >= 1
        assert any("RCON timeout must be positive" in error for error in errors)


class TestDaemonConfigGlobal:
    """Test global daemon configuration functions"""
    
    def setup_method(self):
        """Reset configuration before each test"""
        reset_daemon_config()
    
    def teardown_method(self):
        """Reset configuration after each test"""
        reset_daemon_config()
    
    def test_get_daemon_config_default(self):
        """Test getting default daemon configuration"""
        config = get_daemon_config()
        
        assert isinstance(config, DaemonConfig)
        assert config.daemon_mode == DaemonMode.DOUBLE_FORK
        assert config.enable_process_persistence is True

    def test_set_and_get_daemon_config(self):
        """Test setting and getting daemon configuration"""
        custom_config = DaemonConfig(
            daemon_mode=DaemonMode.SUBPROCESS_DAEMON,
            monitoring_interval_seconds=30
        )
        
        set_daemon_config(custom_config)
        retrieved_config = get_daemon_config()
        
        assert retrieved_config is custom_config
        assert retrieved_config.daemon_mode == DaemonMode.SUBPROCESS_DAEMON
        assert retrieved_config.monitoring_interval_seconds == 30

    def test_validate_daemon_configuration_success(self):
        """Test successful daemon configuration validation"""
        valid_config = DaemonConfig()
        set_daemon_config(valid_config)
        
        errors = validate_daemon_configuration()
        assert len(errors) == 0

    def test_validate_daemon_configuration_failure(self):
        """Test daemon configuration validation with errors"""
        invalid_config = DaemonConfig(
            enable_process_persistence=False,
            enable_auto_recovery=True
        )
        set_daemon_config(invalid_config)
        
        errors = validate_daemon_configuration()
        assert len(errors) > 0
        assert any("Auto recovery requires process persistence" in error for error in errors)

    def test_reset_daemon_config(self):
        """Test resetting daemon configuration"""
        # Set custom configuration
        custom_config = DaemonConfig(monitoring_interval_seconds=99)
        set_daemon_config(custom_config)
        
        # Verify it's set
        assert get_daemon_config().monitoring_interval_seconds == 99
        
        # Reset and verify default
        reset_daemon_config()
        
        # Should create new default config
        new_config = get_daemon_config()
        assert new_config.monitoring_interval_seconds == 5  # Default value

    def test_environment_variable_parsing(self):
        """Test parsing of various environment variable types"""
        env_vars = {
            # Boolean values
            'DAEMON_ENABLE_PERSISTENCE': 'true',
            'DAEMON_ENABLE_MONITORING': 'false',
            'DAEMON_VERIFY_DETACHMENT': '1',
            'DAEMON_SECURE_ENVIRONMENT': '0',
            'DAEMON_ENABLE_LOGS': 'yes',
            'DAEMON_ENABLE_ISOLATION': 'no',
            
            # Integer values
            'DAEMON_MONITORING_INTERVAL': '15',
            'DAEMON_STARTUP_TIMEOUT': '45',
            'DAEMON_LOG_ROTATION_SIZE': '200',
            
            # String values
            'DAEMON_MODE': 'subprocess_daemon',
            'DAEMON_LOG_LEVEL': 'warning',
            
            # Resource limits
            'DAEMON_MAX_MEMORY_MB': '1024',
            'DAEMON_MAX_CPU_PERCENT': '60.5',
            'DAEMON_MAX_OPEN_FILES': '512'
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            config = DaemonConfig.from_environment()
            
            # Verify boolean parsing
            assert config.enable_process_persistence is True
            assert config.enable_process_monitoring is False
            assert config.verify_detachment is True
            assert config.secure_environment is False
            assert config.enable_daemon_logs is True
            assert config.enable_process_isolation is False
            
            # Verify integer parsing
            assert config.monitoring_interval_seconds == 15
            assert config.process_startup_timeout_seconds == 45
            assert config.log_rotation_size_mb == 200
            
            # Verify string parsing
            assert config.daemon_mode == DaemonMode.SUBPROCESS_DAEMON
            assert config.log_level == LogLevel.WARNING
            
            # Verify resource limits
            assert config.resource_limits.max_memory_mb == 1024
            assert config.resource_limits.max_cpu_percent == 60.5
            assert config.resource_limits.max_open_files == 512

    def test_pid_directory_from_environment(self):
        """Test PID directory configuration from environment"""
        with tempfile.TemporaryDirectory() as temp_dir:
            env_vars = {
                'DAEMON_PID_DIRECTORY': temp_dir
            }
            
            with patch.dict(os.environ, env_vars, clear=False):
                config = DaemonConfig.from_environment()
                
                assert config.pid_file_directory == Path(temp_dir)
                assert config.pid_file_directory.exists()
                assert config.pid_file_directory.is_dir()

    def test_invalid_environment_values(self):
        """Test handling of invalid environment variable values"""
        env_vars = {
            'DAEMON_MONITORING_INTERVAL': 'invalid_number',
            'DAEMON_MAX_MEMORY_MB': 'not_a_number'
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            # Should handle gracefully and use defaults
            with pytest.raises((ValueError, ValidationError)):
                DaemonConfig.from_environment()