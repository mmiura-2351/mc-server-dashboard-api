"""
Test coverage for app/core/config.py
Tests focus on configuration validation, field validators, and property methods
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


class TestSettingsValidators:
    """Test cases for Settings field validators"""

    def test_validate_secret_key_too_short(self):
        """Test SECRET_KEY validation with short key (line 70)"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="short",  # Less than 32 characters
                DATABASE_URL="sqlite:///test.db"
            )
        
        assert "SECRET_KEY must be at least 32 characters long" in str(exc_info.value)

    def test_validate_secret_key_weak_values(self):
        """Test SECRET_KEY validation with weak values"""
        weak_keys = [
            "your-secret-key-that-is-long-enough-but-weak",
            "secret-key-that-is-very-long-but-weak",
            "default-secret-key-for-development-use",
            "change-me-to-a-secure-secret-key-value"
        ]
        
        for weak_key in weak_keys:
            with pytest.raises(ValidationError) as exc_info:
                Settings(
                    SECRET_KEY=weak_key,
                    DATABASE_URL="sqlite:///test.db"
                )
            
            assert "SECRET_KEY cannot be a default or weak value" in str(exc_info.value)

    def test_validate_secret_key_valid(self):
        """Test SECRET_KEY validation with valid key"""
        valid_key = "this-is-a-very-secure-secret-key-with-sufficient-length"
        
        settings = Settings(
            SECRET_KEY=valid_key,
            DATABASE_URL="sqlite:///test.db"
        )
        
        assert settings.SECRET_KEY == valid_key

    def test_validate_cors_for_production_localhost_error(self):
        """Test CORS validation for production environment (line 78)"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                ENVIRONMENT="production",
                CORS_ORIGINS="https://example.com,http://localhost:3000"
            )
        
        assert "CORS_ORIGINS should not include localhost in production" in str(exc_info.value)

    def test_validate_cors_for_production_127_error(self):
        """Test CORS validation for production with 127.0.0.1"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                ENVIRONMENT="production",
                CORS_ORIGINS="https://example.com,http://127.0.0.1:3000"
            )
        
        assert "CORS_ORIGINS should not include localhost in production" in str(exc_info.value)

    def test_validate_cors_for_production_valid(self):
        """Test CORS validation for production with valid origins"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            ENVIRONMENT="production",
            CORS_ORIGINS="https://example.com,https://api.example.com"
        )
        
        assert settings.ENVIRONMENT == "production"
        assert settings.CORS_ORIGINS == "https://example.com,https://api.example.com"

    def test_validate_cors_for_development_localhost_allowed(self):
        """Test CORS validation allows localhost in development"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            ENVIRONMENT="development",
            CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
        )
        
        assert settings.ENVIRONMENT == "development"
        assert "localhost" in settings.CORS_ORIGINS

    def test_validate_queue_size_too_small(self):
        """Test SERVER_LOG_QUEUE_SIZE validation with small value (line 86)"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                SERVER_LOG_QUEUE_SIZE=50  # Less than 100
            )
        
        assert "SERVER_LOG_QUEUE_SIZE must be between 100 and 10000" in str(exc_info.value)

    def test_validate_queue_size_too_large(self):
        """Test SERVER_LOG_QUEUE_SIZE validation with large value"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                SERVER_LOG_QUEUE_SIZE=15000  # Greater than 10000
            )
        
        assert "SERVER_LOG_QUEUE_SIZE must be between 100 and 10000" in str(exc_info.value)

    def test_validate_queue_size_valid(self):
        """Test SERVER_LOG_QUEUE_SIZE validation with valid value"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            SERVER_LOG_QUEUE_SIZE=500
        )
        
        assert settings.SERVER_LOG_QUEUE_SIZE == 500

    def test_validate_java_timeout_too_small(self):
        """Test JAVA_CHECK_TIMEOUT validation with small value (line 94)"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                JAVA_CHECK_TIMEOUT=0  # Less than 1
            )
        
        assert "JAVA_CHECK_TIMEOUT must be between 1 and 60 seconds" in str(exc_info.value)

    def test_validate_java_timeout_too_large(self):
        """Test JAVA_CHECK_TIMEOUT validation with large value"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                JAVA_CHECK_TIMEOUT=120  # Greater than 60
            )
        
        assert "JAVA_CHECK_TIMEOUT must be between 1 and 60 seconds" in str(exc_info.value)

    def test_validate_java_timeout_valid(self):
        """Test JAVA_CHECK_TIMEOUT validation with valid value"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            JAVA_CHECK_TIMEOUT=10
        )
        
        assert settings.JAVA_CHECK_TIMEOUT == 10

    def test_validate_db_retries_too_small(self):
        """Test DATABASE_MAX_RETRIES validation with small value (line 104)"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                DATABASE_MAX_RETRIES=0  # Less than 1
            )
        
        assert "DATABASE_MAX_RETRIES must be between 1 and 10" in str(exc_info.value)

    def test_validate_db_retries_too_large(self):
        """Test DATABASE_MAX_RETRIES validation with large value"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                DATABASE_MAX_RETRIES=15  # Greater than 10
            )
        
        assert "DATABASE_MAX_RETRIES must be between 1 and 10" in str(exc_info.value)

    def test_validate_db_retries_valid(self):
        """Test DATABASE_MAX_RETRIES validation with valid value"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            DATABASE_MAX_RETRIES=3
        )
        
        assert settings.DATABASE_MAX_RETRIES == 3

    def test_validate_db_backoff_too_small(self):
        """Test DATABASE_RETRY_BACKOFF validation with small value (line 111)"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                DATABASE_RETRY_BACKOFF=0.005  # Less than 0.01
            )
        
        assert "DATABASE_RETRY_BACKOFF must be between 0.01 and 5.0 seconds" in str(exc_info.value)

    def test_validate_db_backoff_too_large(self):
        """Test DATABASE_RETRY_BACKOFF validation with large value"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                DATABASE_RETRY_BACKOFF=10.0  # Greater than 5.0
            )
        
        assert "DATABASE_RETRY_BACKOFF must be between 0.01 and 5.0 seconds" in str(exc_info.value)

    def test_validate_db_backoff_valid(self):
        """Test DATABASE_RETRY_BACKOFF validation with valid value"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            DATABASE_RETRY_BACKOFF=0.5
        )
        
        assert settings.DATABASE_RETRY_BACKOFF == 0.5

    def test_validate_db_batch_size_too_small(self):
        """Test DATABASE_BATCH_SIZE validation with small value (line 119)"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                DATABASE_BATCH_SIZE=5  # Less than 10
            )
        
        assert "DATABASE_BATCH_SIZE must be between 10 and 1000" in str(exc_info.value)

    def test_validate_db_batch_size_too_large(self):
        """Test DATABASE_BATCH_SIZE validation with large value"""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
                DATABASE_URL="sqlite:///test.db",
                DATABASE_BATCH_SIZE=2000  # Greater than 1000
            )
        
        assert "DATABASE_BATCH_SIZE must be between 10 and 1000" in str(exc_info.value)

    def test_validate_db_batch_size_valid(self):
        """Test DATABASE_BATCH_SIZE validation with valid value"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            DATABASE_BATCH_SIZE=100
        )
        
        assert settings.DATABASE_BATCH_SIZE == 100


class TestSettingsProperties:
    """Test cases for Settings property methods"""

    def test_cors_origins_list_empty(self):
        """Test cors_origins_list property with empty CORS_ORIGINS (line 124)"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            CORS_ORIGINS=""
        )
        
        assert settings.cors_origins_list == []

    def test_cors_origins_list_single(self):
        """Test cors_origins_list property with single origin"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            CORS_ORIGINS="http://localhost:3000"
        )
        
        assert settings.cors_origins_list == ["http://localhost:3000"]

    def test_cors_origins_list_multiple(self):
        """Test cors_origins_list property with multiple origins"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            CORS_ORIGINS="http://localhost:3000,https://example.com,http://127.0.0.1:3000"
        )
        
        expected = ["http://localhost:3000", "https://example.com", "http://127.0.0.1:3000"]
        assert settings.cors_origins_list == expected

    def test_cors_origins_list_with_spaces(self):
        """Test cors_origins_list property with spaces around origins"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            CORS_ORIGINS=" http://localhost:3000 , https://example.com , http://127.0.0.1:3000 "
        )
        
        expected = ["http://localhost:3000", "https://example.com", "http://127.0.0.1:3000"]
        assert settings.cors_origins_list == expected

    def test_cors_origins_list_with_empty_entries(self):
        """Test cors_origins_list property filters out empty entries"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            CORS_ORIGINS="http://localhost:3000,,https://example.com,"
        )
        
        expected = ["http://localhost:3000", "https://example.com"]
        assert settings.cors_origins_list == expected

    def test_is_development_true(self):
        """Test is_development property returns True for development environment"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            ENVIRONMENT="development"
        )
        
        assert settings.is_development is True

    def test_is_development_false(self):
        """Test is_development property returns False for non-development environment"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            ENVIRONMENT="production",
            CORS_ORIGINS="https://example.com"  # Valid production CORS
        )
        
        assert settings.is_development is False

    def test_is_development_case_insensitive(self):
        """Test is_development property is case insensitive"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            ENVIRONMENT="DEVELOPMENT"
        )
        
        assert settings.is_development is True

    def test_is_production_true(self):
        """Test is_production property returns True for production environment (line 131)"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            ENVIRONMENT="production",
            CORS_ORIGINS="https://example.com"  # Valid production CORS
        )
        
        assert settings.is_production is True

    def test_is_production_false(self):
        """Test is_production property returns False for non-production environment"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            ENVIRONMENT="development"
        )
        
        assert settings.is_production is False

    def test_is_production_case_insensitive(self):
        """Test is_production property is case insensitive"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            ENVIRONMENT="PRODUCTION",
            CORS_ORIGINS="https://example.com"  # Valid production CORS
        )
        
        assert settings.is_production is True

    def test_java_discovery_paths_list_empty(self):
        """Test java_discovery_paths_list property with empty paths"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            JAVA_DISCOVERY_PATHS=""
        )
        
        assert settings.java_discovery_paths_list == []

    def test_java_discovery_paths_list_single(self):
        """Test java_discovery_paths_list property with single path"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            JAVA_DISCOVERY_PATHS="/usr/bin"
        )
        
        assert settings.java_discovery_paths_list == ["/usr/bin"]

    def test_java_discovery_paths_list_multiple(self):
        """Test java_discovery_paths_list property with multiple paths"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            JAVA_DISCOVERY_PATHS="/usr/bin,/opt/java,/usr/local/bin"
        )
        
        expected = ["/usr/bin", "/opt/java", "/usr/local/bin"]
        assert settings.java_discovery_paths_list == expected

    def test_java_discovery_paths_list_with_spaces(self):
        """Test java_discovery_paths_list property with spaces around paths"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            JAVA_DISCOVERY_PATHS=" /usr/bin , /opt/java , /usr/local/bin "
        )
        
        expected = ["/usr/bin", "/opt/java", "/usr/local/bin"]
        assert settings.java_discovery_paths_list == expected


class TestGetJavaPath:
    """Test cases for get_java_path method"""

    def test_get_java_path_java_8(self):
        """Test get_java_path for Java 8"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            JAVA_8_PATH="/usr/lib/jvm/java-8-openjdk/bin/java"
        )
        
        result = settings.get_java_path(8)
        assert result == "/usr/lib/jvm/java-8-openjdk/bin/java"

    def test_get_java_path_java_17(self):
        """Test get_java_path for Java 17"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            JAVA_17_PATH="/usr/lib/jvm/java-17-openjdk/bin/java"
        )
        
        result = settings.get_java_path(17)
        assert result == "/usr/lib/jvm/java-17-openjdk/bin/java"

    def test_get_java_path_unsupported_version(self):
        """Test get_java_path for unsupported Java version"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db"
        )
        
        result = settings.get_java_path(11)  # Unsupported version
        assert result is None

    def test_get_java_path_empty_path(self):
        """Test get_java_path when configured path is empty"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            JAVA_8_PATH=""  # Empty path
        )
        
        result = settings.get_java_path(8)
        assert result is None

    def test_get_java_path_all_versions(self):
        """Test get_java_path for all supported Java versions"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            JAVA_8_PATH="/java8",
            JAVA_16_PATH="/java16",
            JAVA_17_PATH="/java17",
            JAVA_21_PATH="/java21"
        )
        
        assert settings.get_java_path(8) == "/java8"
        assert settings.get_java_path(16) == "/java16"
        assert settings.get_java_path(17) == "/java17"
        assert settings.get_java_path(21) == "/java21"


class TestSettingsDefaults:
    """Test cases for Settings default values"""

    def test_default_values(self):
        """Test Settings default values are correctly set"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db"
        )
        
        # Test default values
        assert settings.ALGORITHM == "HS256"
        assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 60  # Environment variable override
        assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 30
        assert settings.SERVER_LOG_QUEUE_SIZE == 500
        assert settings.JAVA_CHECK_TIMEOUT == 5
        assert settings.DATABASE_MAX_RETRIES == 3
        assert settings.DATABASE_RETRY_BACKOFF == 0.1
        assert settings.DATABASE_BATCH_SIZE == 100
        assert settings.ENVIRONMENT == "development"
        
        # Test new process persistence settings
        assert settings.KEEP_SERVERS_ON_SHUTDOWN is True
        assert settings.AUTO_SYNC_ON_STARTUP is True

    def test_empty_java_paths_default(self):
        """Test Java path fields default to empty string"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db"
        )
        
        assert settings.JAVA_DISCOVERY_PATHS == ""
        assert settings.JAVA_8_PATH == ""
        assert settings.JAVA_16_PATH == ""
        assert settings.JAVA_17_PATH == ""
        assert settings.JAVA_21_PATH == ""


class TestProcessPersistenceSettings:
    """Test cases for new process persistence settings"""

    def test_keep_servers_on_shutdown_true(self):
        """Test KEEP_SERVERS_ON_SHUTDOWN can be set to True"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            KEEP_SERVERS_ON_SHUTDOWN=True
        )
        
        assert settings.KEEP_SERVERS_ON_SHUTDOWN is True

    def test_keep_servers_on_shutdown_false(self):
        """Test KEEP_SERVERS_ON_SHUTDOWN can be set to False"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            KEEP_SERVERS_ON_SHUTDOWN=False
        )
        
        assert settings.KEEP_SERVERS_ON_SHUTDOWN is False

    def test_auto_sync_on_startup_true(self):
        """Test AUTO_SYNC_ON_STARTUP can be set to True"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            AUTO_SYNC_ON_STARTUP=True
        )
        
        assert settings.AUTO_SYNC_ON_STARTUP is True

    def test_auto_sync_on_startup_false(self):
        """Test AUTO_SYNC_ON_STARTUP can be set to False"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db",
            AUTO_SYNC_ON_STARTUP=False
        )
        
        assert settings.AUTO_SYNC_ON_STARTUP is False

    def test_process_persistence_defaults(self):
        """Test process persistence settings have correct defaults"""
        settings = Settings(
            SECRET_KEY="this-is-a-very-secure-secret-key-with-sufficient-length",
            DATABASE_URL="sqlite:///test.db"
        )
        
        # Both should default to True for production-ready behavior
        assert settings.KEEP_SERVERS_ON_SHUTDOWN is True
        assert settings.AUTO_SYNC_ON_STARTUP is True


class TestSettingsGlobalInstance:
    """Test cases for global settings instance"""

    def test_global_settings_exists(self):
        """Test that global settings instance exists"""
        from app.core.config import settings
        
        assert settings is not None
        assert isinstance(settings, Settings)