"""API configuration loaded from environment variables."""

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    """Configuration for HTTP API server.

    All values loaded from environment variables with sensible defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # CORS configuration
    cors_origins: List[str] = ["http://localhost:3000"]

    # API key authentication (optional)
    api_key_enabled: bool = False
    api_keys: List[str] | None = None

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window: int = 60  # seconds
    rate_limit_backend: str = "memory"  # "memory" or "redis"
    redis_url: str | None = None

    @field_validator("cors_origins")
    @classmethod
    def parse_cors_origins(cls, v: str | List[str]) -> List[str]:
        """Parse comma-separated string or return list as-is."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("api_keys")
    @classmethod
    def parse_api_keys(cls, v: str | List[str] | None) -> List[str] | None:
        """Parse comma-separated string or return list as-is."""
        if v is None:
            return None
        if isinstance(v, str):
            return [key.strip() for key in v.split(",") if key.strip()]
        return v

    @property
    def public_endpoints(self) -> List[str]:
        """List of endpoints that bypass authentication."""
        return ["/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"]


@lru_cache(maxsize=1)
def get_settings() -> APISettings:
    """Get cached API settings singleton."""
    return APISettings()
