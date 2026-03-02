"""Mailbox CRUD operations for async subagent result delivery.

Stateless module-level async functions following the existing manager pattern.
Each function accepts ``db: AsyncSession`` as its first parameter.

The mailbox collects subagent outcomes (result / failed) and delivers them
to continuation sessions via ``drain_undelivered``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import MailboxMessage
from netherbrain.agent_runtime.models.enums import MailboxSourceType


async def post_message(
    db: AsyncSession,
    *,
    conversation_id: str,
    source_session_id: str,
    source_type: MailboxSourceType,
    subagent_name: str,
) -> MailboxMessage:
    """Post a new message to a conversation's mailbox.

    Called by the coordinator when an async_subagent session reaches
    a terminal state (committed or failed).
    """
    row = MailboxMessage(
        message_id=uuid.uuid4().hex,
        conversation_id=conversation_id,
        source_session_id=source_session_id,
        source_type=source_type,
        subagent_name=subagent_name,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def drain_undelivered(
    db: AsyncSession,
    *,
    conversation_id: str,
    delivered_to: str,
) -> list[MailboxMessage]:
    """Atomically claim and return all undelivered messages.

    Uses UPDATE ... RETURNING to atomically mark messages as delivered,
    preventing duplicate delivery even under concurrent fire requests.

    Parameters
    ----------
    conversation_id:
        The conversation whose mailbox to drain.
    delivered_to:
        The session ID that will consume these messages.

    Returns
    -------
    list[MailboxMessage]
        The claimed messages (now marked with ``delivered_to``).
        Empty list if no pending messages.
    """
    stmt = (
        update(MailboxMessage)
        .where(
            MailboxMessage.conversation_id == conversation_id,
            MailboxMessage.delivered_to.is_(None),
        )
        .values(delivered_to=delivered_to)
        .returning(MailboxMessage)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    await db.commit()
    return rows


async def query_mailbox(
    db: AsyncSession,
    *,
    conversation_id: str,
    pending_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[MailboxMessage]:
    """Query mailbox messages for a conversation.

    Returns messages ordered by creation time (oldest first).
    """
    stmt = (
        select(MailboxMessage)
        .where(MailboxMessage.conversation_id == conversation_id)
        .order_by(MailboxMessage.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    if pending_only:
        stmt = stmt.where(MailboxMessage.delivered_to.is_(None))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_pending(
    db: AsyncSession,
    *,
    conversation_id: str,
) -> int:
    """Count undelivered messages in a conversation's mailbox."""
    stmt = (
        select(func.count())
        .select_from(MailboxMessage)
        .where(
            MailboxMessage.conversation_id == conversation_id,
            MailboxMessage.delivered_to.is_(None),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one()
