"""Conversation summarization via LLM.

Collects committed session content from a conversation, applies a size budget,
and generates a summary using pydantic-ai Agent with a configurable model.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass

from pydantic_ai import Agent, ModelSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import Conversation, Session
from netherbrain.agent_runtime.managers.conversations import ConversationNotFoundError

logger = logging.getLogger(__name__)

# Maximum raw text budget in bytes (128 KB).
_TEXT_BUDGET = 128 * 1024

_SUMMARY_SYSTEM_PROMPT = (
    "You are a conversation summarizer. Given a conversation between a user and an AI assistant, "
    "write a concise summary in under 200 characters that captures the main topic and outcome. "
    "Use the same language as the conversation. Reply with only the summary text, nothing else."
)


class NoSummaryModelError(Exception):
    """Raised when no summary model is configured and none provided in the request."""

    def __init__(self) -> None:
        super().__init__("No summary model configured.")


class EmptyConversationError(ValueError):
    """Raised when the conversation has no committed sessions to summarize."""

    def __init__(self) -> None:
        super().__init__("Conversation has no committed sessions to summarize.")


@dataclass
class _SessionContent:
    """Extracted text from a single session."""

    index: int
    input_text: str
    output_text: str

    @property
    def total_len(self) -> int:
        return len(self.input_text) + len(self.output_text)


def _extract_input_text(input_data: dict | list | None) -> str:
    """Extract text parts from session input (JSONB)."""
    if input_data is None:
        return ""
    parts: list = input_data if isinstance(input_data, list) else [input_data]
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts)


async def _collect_sessions(db: AsyncSession, conversation_id: str) -> list[_SessionContent]:
    """Load all committed sessions for a conversation, ordered chronologically."""
    stmt = (
        select(Session)
        .where(
            Session.conversation_id == conversation_id,
            Session.status.in_(["committed", "awaiting_tool_results"]),
        )
        .order_by(Session.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    contents: list[_SessionContent] = []
    for i, row in enumerate(rows):
        input_text = _extract_input_text(row.input)
        output_text = row.final_message or ""
        if input_text or output_text:
            contents.append(_SessionContent(index=i, input_text=input_text, output_text=output_text))
    return contents


def _format_session(s: _SessionContent) -> str:
    """Format a single session as User/Assistant text."""
    parts: list[str] = []
    if s.input_text:
        parts.append(f"User: {s.input_text}")
    if s.output_text:
        parts.append(f"Assistant: {s.output_text}")
    return "\n".join(parts)


def _apply_budget(sessions: list[_SessionContent], budget: int = _TEXT_BUDGET) -> str:
    """Build conversation text within a size budget.

    Priority:
    1. Always include the first session (original intent).
    2. Always include the last session (most recent context).
    3. Fill remaining budget from the end, working backwards.
    4. Insert ``[... N sessions omitted ...]`` marker where content was dropped.
    """
    if not sessions:
        return ""

    if len(sessions) == 1:
        return _format_session(sessions[0])

    first_text = _format_session(sessions[0])
    last_text = _format_session(sessions[-1])

    # If only two sessions, just concatenate.
    if len(sessions) == 2:
        return f"{first_text}\n\n{last_text}"[:budget]

    middle = sessions[1:-1]
    included_middle = _select_middle(middle, first_text, last_text, budget)

    # Build final text.
    parts = [first_text]
    omitted = len(middle) - len(included_middle)
    if omitted > 0:
        parts.append(f"[... {omitted} sessions omitted ...]")
    parts.extend(_format_session(s) for s in included_middle)
    parts.append(last_text)

    return "\n\n".join(parts)


def _select_middle(
    middle: list[_SessionContent], first_text: str, last_text: str, budget: int
) -> list[_SessionContent]:
    """Select middle sessions that fit within the remaining budget (newest-first)."""
    used = len(first_text) + len(last_text) + 20
    included: list[_SessionContent] = []
    for s in reversed(middle):
        text = _format_session(s)
        if used + len(text) + 10 <= budget:
            included.append(s)
            used += len(text) + 2
        else:
            break
    included.reverse()
    return included


async def summarize_conversation(
    db: AsyncSession,
    conversation_id: str,
    *,
    model: str | None = None,
    model_settings_dict: dict | None = None,
    settings_model: str | None = None,
    settings_model_settings_json: str | None = None,
) -> Conversation:
    """Generate and store a summary for a conversation.

    Parameters
    ----------
    db:
        Database session.
    conversation_id:
        Target conversation.
    model:
        Per-request model override.
    model_settings_dict:
        Per-request model settings override.
    settings_model:
        Service-level summary model from NetherSettings.
    settings_model_settings_json:
        Service-level model settings JSON string from NetherSettings.

    Returns
    -------
    Updated Conversation row with summary populated.

    Raises
    ------
    ConversationNotFoundError:
        If conversation doesn't exist.
    NoSummaryModelError:
        If no model is configured anywhere.
    EmptyConversationError:
        If conversation has no committed sessions.
    """
    # Load conversation.
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(conversation_id)

    # Resolve model: request body -> settings -> error.
    resolved_model = model or settings_model
    if not resolved_model:
        raise NoSummaryModelError

    # Resolve model settings: request body -> settings -> empty.
    resolved_settings: dict = {}
    if settings_model_settings_json:
        with contextlib.suppress(json.JSONDecodeError):
            resolved_settings = json.loads(settings_model_settings_json)
    if model_settings_dict:
        resolved_settings = {**resolved_settings, **model_settings_dict}

    # Collect session content.
    sessions = await _collect_sessions(db, conversation_id)
    if not sessions:
        raise EmptyConversationError

    conversation_text = _apply_budget(sessions)

    # Call LLM via pydantic-ai Agent.
    agent: Agent[None, str] = Agent(
        resolved_model,  # type: ignore[arg-type]
        system_prompt=_SUMMARY_SYSTEM_PROMPT,
    )
    ms = ModelSettings(**resolved_settings) if resolved_settings else None
    result = await agent.run(
        conversation_text,
        model_settings=ms,
    )
    summary = result.output.strip()

    # Persist summary.
    conversation.summary = summary
    await db.commit()
    await db.refresh(conversation)

    logger.info("Summarized conversation {}: {} chars", conversation_id, len(summary))
    return conversation
