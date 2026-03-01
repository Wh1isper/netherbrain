"""Session endpoints (RPC-style).

Thin HTTP adapter -- delegates to session manager.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from netherbrain.agent_runtime.deps import DbSession, SessionMgr
from netherbrain.agent_runtime.models.api import SessionDetailResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}/get", response_model=SessionDetailResponse)
async def handle_get_session(
    session_id: str,
    db: DbSession,
    manager: SessionMgr,
    include_state: bool = Query(False, description="Include full session state blob."),
    include_display_messages: bool = Query(False, description="Include display messages."),
) -> dict:
    try:
        result = await manager.get_session(
            db,
            session_id,
            include_state=include_state,
            include_display_messages=include_display_messages,
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Session '{session_id}' not found.") from None

    # Convert state model to dict for response serialisation.
    if result.get("state") is not None:
        result["state"] = result["state"].model_dump()

    return result
