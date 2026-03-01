"""Input part models for user-submitted content.

Defines the wire-format for user input as described in
spec/agent_runtime/07-api.md (Input Format section).

Input is a list of content parts.  Each part has a ``type`` that determines
which field carries the payload, and an optional ``mode`` that controls how
the part is delivered to the model (write to file vs. pass inline).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from netherbrain.agent_runtime.models.enums import ContentMode, InputPartType


class InputPart(BaseModel):
    """A single content part in user input.

    Exactly one of ``text``, ``url``, ``path``, or ``data`` must be set,
    matching the ``type`` field.

    Attributes
    ----------
    type:
        Part type: text, url, file, or binary.
    text:
        Text content (required when type=text).
    url:
        Resource URL (required when type=url).
    path:
        Project-relative file path (required when type=file).
    data:
        Base64-encoded binary content (required when type=binary).
    mime:
        MIME type hint for url/binary parts.
    mode:
        Delivery mode: ``file`` (default, write to environment) or
        ``inline`` (pass directly to model context).
    """

    type: InputPartType
    text: str | None = None
    url: str | None = None
    path: str | None = None
    data: str | None = None
    mime: str | None = None
    mode: ContentMode = ContentMode.FILE

    @model_validator(mode="after")
    def _validate_payload(self) -> InputPart:
        """Ensure the correct payload field is set for the part type."""
        match self.type:
            case InputPartType.TEXT:
                if not self.text:
                    msg = "text field is required when type='text'"
                    raise ValueError(msg)
            case InputPartType.URL:
                if not self.url:
                    msg = "url field is required when type='url'"
                    raise ValueError(msg)
            case InputPartType.FILE:
                if not self.path:
                    msg = "path field is required when type='file'"
                    raise ValueError(msg)
            case InputPartType.BINARY:
                if not self.data:
                    msg = "data field is required when type='binary'"
                    raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def text_part(text: str) -> InputPart:
    """Create a text input part."""
    return InputPart(type=InputPartType.TEXT, text=text)


def url_part(url: str, *, mime: str | None = None, mode: ContentMode = ContentMode.FILE) -> InputPart:
    """Create a URL input part."""
    return InputPart(type=InputPartType.URL, url=url, mime=mime, mode=mode)


def file_part(path: str, *, mode: ContentMode = ContentMode.FILE) -> InputPart:
    """Create a file input part."""
    return InputPart(type=InputPartType.FILE, path=path, mode=mode)


def binary_part(
    data: str,
    *,
    mime: str = "application/octet-stream",
    mode: ContentMode = ContentMode.FILE,
) -> InputPart:
    """Create a binary input part (base64-encoded data)."""
    return InputPart(type=InputPartType.BINARY, data=data, mime=mime, mode=mode)


# ---------------------------------------------------------------------------
# Deferred tool feedback (used with awaiting_tool_results sessions)
# ---------------------------------------------------------------------------


class UserInteraction(BaseModel):
    """HITL approval decision for a deferred tool call.

    Attributes
    ----------
    tool_call_id:
        The ID of the deferred tool call being approved/denied.
    approved:
        Whether the tool call is approved.
    """

    tool_call_id: str
    approved: bool = True


class ToolResult(BaseModel):
    """External tool execution result provided by the caller.

    Attributes
    ----------
    tool_call_id:
        The ID of the deferred tool call.
    output:
        The result content (string or structured).
    error:
        If set, the tool call failed with this error message.
    """

    tool_call_id: str
    output: str | None = None
    error: str | None = Field(default=None, description="Error message if the tool call failed")
