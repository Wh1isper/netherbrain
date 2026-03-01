"""SQLAlchemy ORM models for PostgreSQL.

These are the single source of truth for the database schema. Alembic reads
``Base.metadata`` to autogenerate migration scripts. The tables correspond to
the data models defined in spec/agent_runtime/01-session.md and
spec/agent_runtime/02-configuration.md.

Uses SQLAlchemy 2.0 declarative style with ``Mapped`` type annotations.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Timezone-aware timestamp type for all datetime columns.
TimestampTZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    """Declarative base with naming convention for constraints."""

    pass


# Apply naming convention to the metadata for deterministic constraint names.
Base.metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Preset(Base):
    __tablename__ = "presets"

    preset_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(Text)
    model: Mapped[dict] = mapped_column(JSONB, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    toolsets: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    environment: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    subagents: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_default: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now(), onupdate=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"

    workspace_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str | None]
    projects: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now(), onupdate=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str | None]
    default_preset_id: Mapped[str | None]
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    status: Mapped[str] = mapped_column(server_default="active")
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now(), onupdate=func.now())


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_conversation_id", "conversation_id"),
        Index("ix_sessions_status", "status"),
    )

    session_id: Mapped[str] = mapped_column(primary_key=True)
    parent_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.session_id", name="fk_sessions_parent_session_id"),
    )
    project_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(server_default="created")
    run_summary: Mapped[dict | None] = mapped_column(JSONB)

    # SessionMetadata fields (flattened for queryability)
    session_type: Mapped[str] = mapped_column(server_default="agent")
    transport: Mapped[str] = mapped_column(server_default="sse")
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id", name="fk_sessions_conversation_id"),
    )
    spawned_by: Mapped[str | None]
    preset_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())


class MailboxMessage(Base):
    __tablename__ = "mailbox"
    __table_args__ = (Index("ix_mailbox_conversation_id", "conversation_id"),)

    message_id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id", name="fk_mailbox_conversation_id"),
    )
    source_session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id", name="fk_mailbox_source_session_id"),
    )
    source_type: Mapped[str]
    subagent_name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())
    delivered_to: Mapped[str | None]
