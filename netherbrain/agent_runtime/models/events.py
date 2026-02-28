"""Protocol event models.

Defines the event envelope and type constants.  Specific payload schemas will
be added when the event processor is implemented.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from netherbrain.agent_runtime.models.enums import EventType


class ProtocolEvent(BaseModel):
    """Wire-format event envelope sent over SSE / Redis Stream."""

    event_id: str
    event_type: EventType
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    agent_id: str = "main"
    payload: dict[str, Any] = Field(default_factory=dict)
