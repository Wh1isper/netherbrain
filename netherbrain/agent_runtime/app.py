import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.routing import APIRouter
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Netherbrain Agent Runtime")

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
# Override with UI_DIR env var if needed.
# ---------------------------------------------------------------------------
_UI_DIR = Path(os.getenv("UI_DIR", "ui/dist"))

if _UI_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_UI_DIR / "assets"), name="ui-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve the SPA index.html for all unmatched routes (client-side routing)."""
        file_path = _UI_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_UI_DIR / "index.html")
