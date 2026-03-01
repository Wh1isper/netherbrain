import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.routing import APIRouter
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sse_starlette.sse import AppStatus

from netherbrain.agent_runtime.db.engine import create_engine, create_session_factory
from netherbrain.agent_runtime.log import setup_logging
from netherbrain.agent_runtime.managers.sessions import SessionManager
from netherbrain.agent_runtime.registry import SessionRegistry
from netherbrain.agent_runtime.settings import NetherSettings, get_settings
from netherbrain.agent_runtime.store.base import StateStore
from netherbrain.agent_runtime.store.local import LocalStateStore

# ---------------------------------------------------------------------------
# Shared singletons initialised during lifespan
# ---------------------------------------------------------------------------
registry = SessionRegistry()


def _create_state_store(settings: NetherSettings) -> StateStore:
    """Create the state store backend based on configuration."""
    if settings.state_store == "s3":
        # TODO: S3StateStore implementation
        msg = "S3 state store not yet implemented"
        raise NotImplementedError(msg)
    return LocalStateStore(settings.data_root, prefix=settings.data_prefix)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # -- Startup ---------------------------------------------------------------
    settings = get_settings()
    setup_logging(settings.log_level)

    auth_token = settings.resolve_auth_token()
    if not settings.auth_token:
        logger.warning("No NETHER_AUTH_TOKEN set -- generated token: {}", auth_token)

    logger.info("Agent Runtime starting (host={}, port={})", settings.host, settings.port)
    prefix_info = f", prefix={settings.data_prefix}" if settings.data_prefix else ""
    logger.info("Data root: {} (store={}{})", settings.data_root, settings.state_store, prefix_info)

    # -- Initialise state fields (always present, possibly None) ----------------
    _app.state.db_engine = None
    _app.state.db_session_factory = None
    _app.state.redis = None
    _app.state.session_manager = None

    # -- Database --------------------------------------------------------------
    if settings.database_url:
        engine = create_engine(settings.database_url)
        _app.state.db_engine = engine
        _app.state.db_session_factory = create_session_factory(engine)
        logger.info("PostgreSQL: connected (pool_size=5, max_overflow=10)")
    else:
        logger.warning("NETHER_DATABASE_URL not set -- database features disabled")

    # -- Redis -----------------------------------------------------------------
    if settings.redis_url:
        _app.state.redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        logger.info("Redis: connected")
    else:
        logger.warning("NETHER_REDIS_URL not set -- stream transport disabled")

    # -- SSE -------------------------------------------------------------------
    # Let SSE streams complete naturally on shutdown instead of being
    # terminated immediately.  Uvicorn's graceful shutdown will wait for
    # open connections to close, giving active streams time to finish.
    AppStatus.disable_automatic_graceful_drain()

    # -- Session manager -------------------------------------------------------
    if _app.state.db_session_factory is not None:
        store = _create_state_store(settings)
        _app.state.session_manager = SessionManager(store=store, registry=registry)
        logger.info("SessionManager: initialised")

        # Startup recovery: mark orphaned sessions as failed.
        async with _app.state.db_session_factory() as db:
            recovered = await SessionManager.recover_orphaned_sessions(db)
            if recovered > 0:
                logger.info("Startup recovery: {} orphaned sessions marked as failed", recovered)

    yield

    # -- Shutdown --------------------------------------------------------------
    logger.info("Agent Runtime shutting down (active_sessions={})", registry.active_count)

    # 1. Stop accepting new sessions.
    registry.begin_shutdown()

    # 2. Wait for active sessions to complete naturally.
    if registry.active_count > 0:
        timeout = settings.graceful_shutdown_timeout
        logger.info("Waiting for {} active sessions to finish (timeout={}s)...", registry.active_count, timeout)
        drained = await registry.wait_until_drained(timeout=timeout)
        if not drained:
            # Last resort: force-interrupt remaining sessions.
            interrupted = registry.interrupt_all()
            logger.warning("Force-interrupted {} sessions after timeout", interrupted)
            await registry.wait_until_drained(timeout=5.0)

    # 3. Signal SSE streams to close.  Must happen AFTER session drain so
    #    that SSE connections can deliver the terminal event before closing.
    AppStatus.should_exit = True
    logger.info("SSE: signalled streams to close")

    # TODO: flush pending mailbox messages

    # Close Redis client (returns pooled connections).
    if _app.state.redis is not None:
        await _app.state.redis.aclose()
        logger.info("Redis: closed")

    # Dispose DB engine (closes all pooled connections).
    if _app.state.db_engine is not None:
        await _app.state.db_engine.dispose()
        logger.info("PostgreSQL: disposed")


app = FastAPI(title="Netherbrain Agent Runtime", lifespan=lifespan)

# ---------------------------------------------------------------------------
# API router -- all backend endpoints live under /api
# ---------------------------------------------------------------------------
api = APIRouter(prefix="/api")


@api.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# -- CRUD routers ------------------------------------------------------------
from netherbrain.agent_runtime.routers.conversations import router as conversations_router  # noqa: E402
from netherbrain.agent_runtime.routers.presets import router as presets_router  # noqa: E402
from netherbrain.agent_runtime.routers.sessions import router as sessions_router  # noqa: E402
from netherbrain.agent_runtime.routers.workspaces import router as workspaces_router  # noqa: E402

api.include_router(presets_router)
api.include_router(workspaces_router)
api.include_router(conversations_router)
api.include_router(sessions_router)

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
