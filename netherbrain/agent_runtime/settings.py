"""Service configuration loaded from NETHER_* environment variables."""

from __future__ import annotations

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
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Logging ---------------------------------------------------------------
    log_level: str = "INFO"

    # -- Infrastructure --------------------------------------------------------
    database_url: str | None = None
    """PostgreSQL connection string (asyncpg).  Required for full operation."""

    redis_url: str | None = None
    """Redis connection string.  Required for stream transport."""

    # -- Data storage ----------------------------------------------------------
    data_root: str = "./data"
    """Unified root directory for all managed data (projects, session state)."""

    data_prefix: str | None = None
    """Optional namespace prefix inserted into all data paths.

    When set, all paths become ``{data_root}/{data_prefix}/...``.
    Useful for multi-tenant or organizational separation.
    """

    state_store: Literal["local", "s3"] = "local"

    # S3 (only when state_store = "s3")
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: SecretStr | None = None
    s3_path_style: bool = False
    """Use path-style addressing (required by MinIO and some S3-compatible services)."""

    # -- Auth ------------------------------------------------------------------
    auth_token: str = ""
    """Bearer token for API access.  Required for agent startup.

    Also used to derive the JWT signing secret (HMAC-SHA256) so no
    separate secret management is needed.
    """

    jwt_expiry_days: int = 7
    """JWT token expiry in days.  Default: 7 (homelab-friendly)."""

    # -- Self-referencing API --------------------------------------------------
    api_base_url: str | None = None
    """Base URL for the agent-runtime's own API (self-referencing tool calls).

    When not set, derived as ``http://127.0.0.1:{port}`` at runtime.
    """

    # -- Summary ---------------------------------------------------------------
    summary_model: str | None = None
    """Provider-qualified model name for conversation summaries.

    When not set, the summarize endpoint returns 501 Not Implemented.
    Example: ``openai:gpt-4.1-mini``, ``anthropic:claude-sonnet-4-20250514``.
    """

    summary_model_settings: str | None = None
    """JSON string of ModelSettings overrides for the summary model.

    Example: ``{"temperature": 0.3}``.
    """

    # -- Server ----------------------------------------------------------------
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 9001
    graceful_shutdown_timeout: int = 7200
    """Seconds to wait for active sessions to finish during shutdown.

    Sessions can run up to 2 hours, so the default matches that ceiling.
    After this timeout, remaining sessions are force-interrupted.
    Note: uvicorn's ``--timeout-graceful-shutdown`` must be >= this value
    for the wait to be effective.
    """

    # -- Helpers ---------------------------------------------------------------

    @property
    def jwt_secret(self) -> str:
        """Derive JWT signing secret from auth_token via HMAC-SHA256.

        Using a derived key ensures the raw auth_token cannot be recovered
        from a JWT, while keeping configuration to a single secret.
        """
        import hashlib
        import hmac

        return hmac.new(
            self.auth_token.encode(),
            b"netherbrain-jwt-signing-key",
            hashlib.sha256,
        ).hexdigest()


def get_settings() -> NetherSettings:
    """Return a cached settings instance.

    Reads from environment variables and ``.env`` on first call, then returns
    the same object.  Call ``get_settings.cache_clear()`` in tests to force a
    re-read after overriding env vars.
    """
    return _get_settings_cached()


def _get_settings_cached() -> NetherSettings:
    """Inner function wrapped by lru_cache (allows type-safe cache_clear)."""
    return NetherSettings()


# Apply lru_cache at runtime so the function is only called once.
from functools import lru_cache  # noqa: E402

_get_settings_cached = lru_cache(maxsize=1)(_get_settings_cached)
