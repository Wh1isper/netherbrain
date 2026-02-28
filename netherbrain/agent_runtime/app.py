import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.routing import APIRouter
from fastapi.staticfiles import StaticFiles
from loguru import logger

from netherbrain.agent_runtime.log import setup_logging
from netherbrain.agent_runtime.registry import SessionRegistry
from netherbrain.agent_runtime.settings import NetherSettings

# ---------------------------------------------------------------------------
# Settings & logging -- resolved once at import time so that uvicorn workers
# pick them up before the first request.
# ---------------------------------------------------------------------------
settings = NetherSettings()
setup_logging(settings.log_level)

# ---------------------------------------------------------------------------
# Shared singletons initialised during lifespan
# ---------------------------------------------------------------------------
registry = SessionRegistry()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # -- Startup ---------------------------------------------------------------
    auth_token = settings.resolve_auth_token()
    if not settings.auth_token:
        logger.warning("No NETHER_AUTH_TOKEN set -- generated token: {}", auth_token)

    logger.info("Agent Runtime starting (host={}, port={})", settings.host, settings.port)
    logger.info("State store: {} (path={})", settings.state_store, settings.state_store_path)

    if settings.database_url:
        logger.info("PostgreSQL: configured")
    else:
        logger.warning("NETHER_DATABASE_URL not set -- database features disabled")

    if settings.redis_url:
        logger.info("Redis: configured")
    else:
        logger.warning("NETHER_REDIS_URL not set -- stream transport disabled")

    # TODO: initialise DB connection pool, Redis client, run startup recovery

    yield

    # -- Shutdown --------------------------------------------------------------
    logger.info("Agent Runtime shutting down (active_sessions={})", registry.active_count)
    # TODO: graceful shutdown -- interrupt active sessions, close pools


app = FastAPI(title="Netherbrain Agent Runtime", lifespan=lifespan)

# ---------------------------------------------------------------------------
# API router -- all backend endpoints live under /api
# ---------------------------------------------------------------------------
api = APIRouter(prefix="/api")


@api.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api)

# ---------------------------------------------------------------------------
# Static UI serving
# Resolved relative to CWD: project root in dev (make run-agent), /app in Docker.
# Override with NETHER_UI_DIR env var if needed.
# ---------------------------------------------------------------------------
_UI_DIR = Path(os.getenv("NETHER_UI_DIR", "ui/dist"))

if _UI_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_UI_DIR / "assets"), name="ui-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve the SPA index.html for all unmatched routes (client-side routing)."""
        file_path = _UI_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_UI_DIR / "index.html")
