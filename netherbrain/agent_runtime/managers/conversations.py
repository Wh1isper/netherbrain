"""Conversation CRUD operations.

Conversations are created implicitly by the session system (SessionManager),
so this module only provides read and update operations.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import Conversation
from netherbrain.agent_runtime.models.api import ConversationUpdate


class ConversationNotFoundError(LookupError):
    """Raised when a conversation is not found."""


async def list_conversations(
    db: AsyncSession,
    *,
    status: str | None = None,
    metadata_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Conversation]:
    """List conversations with optional filters, newest first.

    Raises ``ValueError`` if ``metadata_contains`` is not valid JSON.
    """
    stmt = select(Conversation).order_by(Conversation.created_at.desc())

    if status is not None:
        stmt = stmt.where(Conversation.status == status)

    if metadata_contains is not None:
        try:
            filter_obj = json.loads(metadata_contains)
        except json.JSONDecodeError as exc:
            msg = f"Invalid JSON in metadata_contains: {exc}"
            raise ValueError(msg) from None
        metadata_col = Conversation.__table__.c.metadata
        stmt = stmt.where(metadata_col.cast(PG_JSONB).contains(filter_obj))

    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_conversation(db: AsyncSession, conversation_id: str) -> Conversation:
    """Get a conversation by ID.  Raises ``ConversationNotFoundError`` if missing."""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(conversation_id)
    return conversation


async def update_conversation(db: AsyncSession, conversation_id: str, body: ConversationUpdate) -> Conversation:
    """Update conversation fields.  Raises ``ConversationNotFoundError`` if missing."""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(conversation_id)

    updates = body.model_dump(exclude_unset=True)
    if "metadata" in updates:
        updates["metadata_"] = updates.pop("metadata")

    for key, value in updates.items():
        setattr(conversation, key, value)

    await db.commit()
    await db.refresh(conversation)
    return conversation
