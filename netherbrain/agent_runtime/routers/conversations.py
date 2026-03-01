"""Conversation endpoints (RPC-style).

Thin HTTP adapter -- delegates to conversation manager and session manager.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from netherbrain.agent_runtime.deps import DbSession, SessionMgr
from netherbrain.agent_runtime.managers.conversations import (
    ConversationNotFoundError,
    get_conversation,
    list_conversations,
    update_conversation,
)
from netherbrain.agent_runtime.models.api import (
    ConversationResponse,
    ConversationUpdate,
    SessionResponse,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/list", response_model=list[ConversationResponse])
async def handle_list_conversations(
    db: DbSession,
    conversation_status: str | None = Query(None, alias="status", description="Filter by status (e.g. 'active')."),
    metadata_contains: str | None = Query(
        None,
        description='JSON string for JSONB containment filter (@>). Example: \'{"source": "discord"}\'.',
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list:
    try:
        return await list_conversations(
            db, status=conversation_status, metadata_contains=metadata_contains, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None


@router.get("/{conversation_id}/get", response_model=ConversationResponse)
async def handle_get_conversation(conversation_id: str, db: DbSession) -> object:
    try:
        return await get_conversation(db, conversation_id)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None


@router.post("/{conversation_id}/update", response_model=ConversationResponse)
async def handle_update_conversation(
    conversation_id: str,
    body: ConversationUpdate,
    db: DbSession,
) -> object:
    try:
        return await update_conversation(db, conversation_id, body)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None


@router.get("/{conversation_id}/sessions", response_model=list[SessionResponse])
async def handle_list_conversation_sessions(
    conversation_id: str,
    db: DbSession,
    manager: SessionMgr,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list:
    try:
        await get_conversation(db, conversation_id)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None

    return await manager.list_sessions(db, conversation_id, limit=limit, offset=offset)


@router.get("/{conversation_id}/turns")
async def handle_get_conversation_turns(
    conversation_id: str,
    db: DbSession,
    manager: SessionMgr,
) -> list[dict]:
    try:
        await get_conversation(db, conversation_id)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None

    return await manager.get_conversation_turns(db, conversation_id)
