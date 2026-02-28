"""Service configuration loaded from NETHER_* environment variables."""

from __future__ import annotations

import secrets
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class NetherSettings(BaseSettings):
    """Netherbrain Agent Runtime settings.

    All fields are read from environment variables with the ``NETHER_`` prefix.
    For example, ``NETHER_LOG_LEVEL=DEBUG`` maps to ``log_level``.

    LLM provider keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...) and tool API
    keys (TAVILY_API_KEY, ...) are **not** managed here -- they are read
    directly by ya-agent-sdk via its own ToolConfig / model conventions.
    """

    model_config = SettingsConfigDict(
        env_prefix="NETHER_",
        case_sensitive=False,
    )

    # -- Logging ---------------------------------------------------------------
    log_level: str = "INFO"

    # -- Infrastructure --------------------------------------------------------
    database_url: str | None = None
    """PostgreSQL connection string (asyncpg).  Required for full operation."""

    redis_url: str | None = None
    """Redis connection string.  Required for stream transport."""

    # -- State store -----------------------------------------------------------
    state_store: Literal["local", "s3"] = "local"
    state_store_path: str = "./data"

    # S3 (only when state_store = "s3")
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: SecretStr | None = None

    # -- Auth ------------------------------------------------------------------
    auth_token: str | None = None
    """Bearer token for API access.  Auto-generated at startup if empty."""

    # -- Server ----------------------------------------------------------------
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8000

    # -- Helpers ---------------------------------------------------------------

    def resolve_auth_token(self) -> str:
        """Return the configured token or generate a random one."""
        if self.auth_token:
            return self.auth_token
        return secrets.token_urlsafe(32)
