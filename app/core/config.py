from typing import List

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


settings = Settings()
