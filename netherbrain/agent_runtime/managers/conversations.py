"""Conversation CRUD and search operations.

Conversations are created implicitly by the session system (SessionManager),
so this module only provides read, update, and search operations.
"""

from __future__ import annotations

import json

from sqlalchemy import String, func, literal, select, union
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import Conversation, Session
from netherbrain.agent_runtime.models.api import ConversationUpdate


class ConversationNotFoundError(LookupError):
    """Raised when a conversation is not found."""


async def list_conversations(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    status: str | None = None,
    metadata_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Conversation]:
    """List conversations with optional filters, newest first.

    When ``user_id`` is provided, only conversations owned by that user are
    returned.  Admins pass ``user_id=None`` to see all.

    Raises ``ValueError`` if ``metadata_contains`` is not valid JSON.
    """
    stmt = select(Conversation).order_by(Conversation.created_at.desc())

    if user_id is not None:
        stmt = stmt.where(Conversation.user_id == user_id)

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


async def get_conversation(
    db: AsyncSession,
    conversation_id: str,
    *,
    user_id: str | None = None,
    is_admin: bool = False,
) -> Conversation:
    """Get a conversation by ID.  Raises ``ConversationNotFoundError`` if missing.

    When ``user_id`` is provided and ``is_admin`` is False, raises
    ``ConversationNotFoundError`` if the conversation belongs to another user
    (returns 404 to avoid leaking existence).
    """
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(conversation_id)
    if user_id is not None and not is_admin and conversation.user_id != user_id:
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


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def search_conversations(
    db: AsyncSession,
    query: str,
    *,
    user_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[tuple[Conversation, str]], int]:
    """Search conversations by keyword across title, summary, and session content.

    Uses PostgreSQL ``ILIKE`` with ``pg_trgm`` GIN indexes for efficient
    substring matching. Multiple terms use AND semantics.

    Parameters
    ----------
    db:
        Database session.
    query:
        Space-separated search terms (AND semantics).
    user_id:
        Scope to this user's conversations. ``None`` = all (admin).
    limit:
        Max results to return.
    offset:
        Pagination offset.

    Returns
    -------
    Tuple of (list of (Conversation, match_source), total_count).
    """
    terms = query.strip().split()
    if not terms:
        return [], 0

    patterns = [f"%{t}%" for t in terms]

    # -- Phase 1: Find matching conversation IDs with match source -----------

    # Ownership filter subquery.
    user_filter = Conversation.user_id == user_id if user_id is not None else literal(True)

    # Direct conversation matches (title, summary).
    conv_conditions = []
    for pat in patterns:
        conv_conditions.append(Conversation.title.ilike(pat) | Conversation.summary.ilike(pat))

    title_match_q = select(
        Conversation.conversation_id,
        literal("title").label("match_source"),
    ).where(user_filter, *conv_conditions)

    # Session content matches (final_message, input::text).
    user_conv_ids = select(Conversation.conversation_id).where(user_filter).scalar_subquery()

    session_conditions = [
        Session.conversation_id.in_(user_conv_ids),
        Session.status.in_(["committed", "awaiting_tool_results"]),
    ]
    for pat in patterns:
        session_conditions.append(Session.final_message.ilike(pat) | Session.input.cast(String).ilike(pat))

    session_match_q = (
        select(
            Session.conversation_id,
            literal("session_content").label("match_source"),
        )
        .where(*session_conditions)
        .distinct()
    )

    # Union both sources.  Title/summary matches take priority.
    combined = union(title_match_q, session_match_q).subquery()

    # Deduplicate: prefer title > summary > session_content.
    source_priority = func.min(combined.c.match_source).label("match_source")
    deduped = select(combined.c.conversation_id, source_priority).group_by(combined.c.conversation_id)

    # -- Count total matches ---------------------------------------------------
    count_q = select(func.count()).select_from(deduped.subquery())
    total = (await db.execute(count_q)).scalar_one()

    if total == 0:
        return [], 0

    # -- Phase 2: Load full conversations ------------------------------------
    deduped_sub = deduped.subquery()

    load_q = (
        select(Conversation, deduped_sub.c.match_source)
        .join(deduped_sub, Conversation.conversation_id == deduped_sub.c.conversation_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = (await db.execute(load_q)).all()
    results = [(row[0], row[1]) for row in rows]
    return results, total
