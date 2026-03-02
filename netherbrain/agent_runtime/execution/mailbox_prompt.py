"""Mailbox message rendering for fire-continuation prompts.

Converts drained mailbox messages (with loaded session content) into
a text prompt that the continuation agent receives as input.
"""

from __future__ import annotations

from dataclasses import dataclass

from netherbrain.agent_runtime.models.enums import MailboxSourceType


@dataclass
class MailboxMessageWithContent:
    """A mailbox message enriched with the source session's output."""

    message_id: str
    source_session_id: str
    source_type: MailboxSourceType
    subagent_name: str
    final_message: str | None


def _render_single(msg: MailboxMessageWithContent) -> str:
    """Render a single mailbox message."""
    if msg.source_type == MailboxSourceType.SUBAGENT_RESULT:
        content = msg.final_message or "(no output)"
        return f"Async subagent '{msg.subagent_name}' (session: {msg.source_session_id}) completed:\n{content}"
    else:
        return f"Async subagent '{msg.subagent_name}' (session: {msg.source_session_id}) failed."


def render_mailbox_prompt(
    messages: list[MailboxMessageWithContent],
    user_input: str | None = None,
) -> str:
    """Render mailbox messages into a continuation prompt.

    Parameters
    ----------
    messages:
        Drained mailbox messages with loaded content.
    user_input:
        Optional additional user message to append.

    Returns
    -------
    str
        Rendered prompt text for the continuation agent.
    """
    if not messages:
        return user_input or ""

    if len(messages) == 1:
        body = _render_single(messages[0])
    else:
        parts: list[str] = ["Async subagent results:"]
        for msg in messages:
            status = "completed" if msg.source_type == MailboxSourceType.SUBAGENT_RESULT else "failed"
            header = f"## {msg.subagent_name} [{status}] (session: {msg.source_session_id})"
            if msg.source_type == MailboxSourceType.SUBAGENT_RESULT:
                content = msg.final_message or "(no output)"
            else:
                content = "Error: subagent execution failed."
            parts.append(f"\n{header}\n{content}")
        body = "\n".join(parts)

    if user_input:
        return f"{body}\n\n---\nUser message:\n{user_input}"
    return body
