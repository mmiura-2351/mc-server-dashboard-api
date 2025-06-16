"""Test configuration validation for security enhancements"""

import os
import pytest
from pydantic import ValidationError


class TestConfigValidation:
    """Test configuration validation"""

    def test_secret_key_minimum_length(self):
        """Test SECRET_KEY minimum length validation"""
        # Set invalid SECRET_KEY
        os.environ["SECRET_KEY"] = "short"
        os.environ["DATABASE_URL"] = "sqlite:///./test.db"
        
        with pytest.raises(ValidationError) as exc_info:
            from app.core.config import Settings
            Settings()
        
        assert "SECRET_KEY must be at least 32 characters long" in str(exc_info.value)

    def test_secret_key_weak_values(self):
        """Test SECRET_KEY weak value validation"""
        weak_values = ["your-secret-key", "secret", "default", "change-me"]
        
        os.environ["DATABASE_URL"] = "sqlite:///./test.db"
        
        for weak_value in weak_values:
            # Pad to meet length requirement
            os.environ["SECRET_KEY"] = weak_value + "x" * (32 - len(weak_value))
            
            with pytest.raises(ValidationError) as exc_info:
                from app.core.config import Settings
                Settings()
            
            assert "SECRET_KEY cannot be a default or weak value" in str(exc_info.value)

    def test_secret_key_valid(self):
        """Test valid SECRET_KEY"""
        os.environ["SECRET_KEY"] = "a" * 32  # Valid 32-character key
        os.environ["DATABASE_URL"] = "sqlite:///./test.db"
        
        from app.core.config import Settings
        settings = Settings()
        
        assert len(settings.SECRET_KEY) >= 32

    def test_cors_origins_production_validation(self):
        """Test CORS origins validation in production"""
        os.environ["SECRET_KEY"] = "a" * 32
        os.environ["DATABASE_URL"] = "sqlite:///./test.db"
        os.environ["ENVIRONMENT"] = "production"
        os.environ["CORS_ORIGINS"] = "http://localhost:3000,http://example.com"
        
        with pytest.raises(ValidationError) as exc_info:
            from app.core.config import Settings
            Settings()
        
        assert "CORS_ORIGINS should not include localhost in production" in str(exc_info.value)

    def test_cors_origins_development_allows_localhost(self):
        """Test CORS origins allows localhost in development"""
        os.environ["SECRET_KEY"] = "a" * 32
        os.environ["DATABASE_URL"] = "sqlite:///./test.db"
        os.environ["ENVIRONMENT"] = "development"
        os.environ["CORS_ORIGINS"] = "http://localhost:3000,http://127.0.0.1:3000"
        
        from app.core.config import Settings
        settings = Settings()
        
        assert "localhost" in settings.CORS_ORIGINS
        assert "127.0.0.1" in settings.CORS_ORIGINS

    def test_cors_origins_production_valid(self):
        """Test valid CORS origins in production"""
        os.environ["SECRET_KEY"] = "a" * 32
        os.environ["DATABASE_URL"] = "sqlite:///./test.db"
        os.environ["ENVIRONMENT"] = "production"
        os.environ["CORS_ORIGINS"] = "https://example.com,https://app.example.com"
        
        from app.core.config import Settings
        settings = Settings()
        
        assert "localhost" not in settings.CORS_ORIGINS
        assert "127.0.0.1" not in settings.CORS_ORIGINS
        assert "example.com" in settings.CORS_ORIGINS

    def teardown_method(self):
        """Clean up environment variables after each test"""
        env_vars = ["SECRET_KEY", "DATABASE_URL", "ENVIRONMENT", "CORS_ORIGINS"]
        for var in env_vars:
            if var in os.environ:
                del os.environ[var]