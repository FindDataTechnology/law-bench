"""Server configuration loaded from .env.

Pydantic settings for FastAPI server (host, port, CORS origins), OpenAI API
credentials, and database URL. Reviewer configs are loaded separately by
agent.config because nodes import them before the app boots.
"""
from __future__ import annotations

from dotenv import load_dotenv
from pydantic_settings import BaseSettings


load_dotenv()


class ServerConfig(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: str = "http://localhost:3000,http://localhost:8000"
    api_key_enabled: bool = False
    api_keys: str = ""
    database_url: str = ""

    class Config:
        env_prefix = ""
        env_file = ".env"
        case_sensitive = False


config = ServerConfig()


def get_server_config() -> ServerConfig:
    return config
