"""Conversation read-only endpoints (RPC-style).

Conversations are created implicitly by the session system, not directly by
users.  This router exposes read-only access for listing and inspecting them.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB

from netherbrain.agent_runtime.db.tables import Conversation
from netherbrain.agent_runtime.deps import DbSession
from netherbrain.agent_runtime.models.api import ConversationResponse

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/list", response_model=list[ConversationResponse])
async def list_conversations(
    db: DbSession,
    conversation_status: str | None = Query(None, alias="status", description="Filter by status (e.g. 'active')."),
    metadata_contains: str | None = Query(
        None,
        description='JSON string for JSONB containment filter (@>). Example: \'{"source": "discord"}\'.',
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[Conversation]:
    """List conversations with optional filters.

    Supports filtering by status and JSONB metadata containment (``@>``).
    Results are ordered by creation time, newest first.
    """
    stmt = select(Conversation).order_by(Conversation.created_at.desc())

    if conversation_status is not None:
        stmt = stmt.where(Conversation.status == conversation_status)

    if metadata_contains is not None:
        try:
            filter_obj = json.loads(metadata_contains)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid JSON in metadata_contains: {exc}",
            ) from None
        # Use PG JSONB containment operator: metadata @> '{"key": "val"}'
        metadata_col = Conversation.__table__.c.metadata
        stmt = stmt.where(metadata_col.cast(PG_JSONB).contains(filter_obj))

    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{conversation_id}/get", response_model=ConversationResponse)
async def get_conversation(conversation_id: str, db: DbSession) -> Conversation:
    """Get a single conversation by ID."""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.")
    return conversation
