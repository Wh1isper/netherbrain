"""Session endpoints (RPC-style).

Thin HTTP adapter -- parses request params, calls managers, translates
domain exceptions to HTTP responses.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from netherbrain.agent_runtime.db.tables import Session as SessionRow
from netherbrain.agent_runtime.deps import DbSession, ExecutionMgr, SessionMgr
from netherbrain.agent_runtime.execution.resolver import (
    NoPresetError,
    ProjectConflictError,
    WorkspaceNotFoundError,
)
from netherbrain.agent_runtime.managers.execution import (
    InputRequiredError,
    NoActiveSessionError,
    SessionContextNotReadyError,
    SteeringTextRequiredError,
)
from netherbrain.agent_runtime.models.api import (
    ExecuteAcceptedResponse,
    SessionDetailResponse,
    SessionExecuteRequest,
    SessionStatusResponse,
    SteerRequest,
)
from netherbrain.agent_runtime.models.enums import SessionStatus, Transport
from netherbrain.agent_runtime.transport.bridge import StreamGoneError, bridge_stream_to_sse

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# POST /sessions/execute
# ---------------------------------------------------------------------------


@router.post("/execute")
async def handle_execute(body: SessionExecuteRequest, db: DbSession, execution: ExecutionMgr):
    """Direct session execution with explicit parameters."""
    try:
        result = await execution.execute_session(
            db,
            preset_id=body.preset_id,
            input_parts=body.input,
            user_interactions=body.user_interactions,
            tool_results=body.tool_results,
            parent_session_id=body.parent_session_id,
            fork=body.fork,
            workspace_id=body.workspace_id,
            project_ids=body.project_ids,
            config_override=body.config_override,
            transport=body.transport,
        )
    except InputRequiredError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    except (NoPresetError, WorkspaceNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except (ProjectConflictError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None

    if result.transport == Transport.STREAM:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=ExecuteAcceptedResponse(
                session_id=result.session_id,
                conversation_id=result.conversation_id,
                stream_key=result.stream_key or "",
            ).model_dump(),
        )

    assert result.sse_transport is not None  # noqa: S101
    return EventSourceResponse(result.sse_transport.event_generator())


# ---------------------------------------------------------------------------
# GET /sessions/{session_id}/get
# ---------------------------------------------------------------------------


@router.get("/{session_id}/get", response_model=SessionDetailResponse)
async def handle_get_session(
    session_id: str,
    db: DbSession,
    manager: SessionMgr,
    include_state: bool = Query(False),
) -> dict:
    try:
        result = await manager.get_session(db, session_id, include_state=include_state)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Session '{session_id}' not found.") from None

    if result.get("state") is not None:
        result["state"] = result["state"].model_dump()
    return result


# ---------------------------------------------------------------------------
# GET /sessions/{session_id}/status
# ---------------------------------------------------------------------------


@router.get("/{session_id}/status", response_model=SessionStatusResponse)
async def handle_get_session_status(session_id: str, db: DbSession, execution: ExecutionMgr) -> SessionStatusResponse:
    """Check session execution status. Registry first, then PG fallback."""
    live_status = execution.get_session_status(session_id)
    if live_status is not None:
        s, transport, stream_key = live_status
        return SessionStatusResponse(session_id=session_id, status=s, transport=transport, stream_key=stream_key)

    row = await db.get(SessionRow, session_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Session '{session_id}' not found.")

    return SessionStatusResponse(
        session_id=session_id,
        status=SessionStatus(row.status),
        transport=Transport(row.transport),
    )


# ---------------------------------------------------------------------------
# GET /sessions/{session_id}/events
# ---------------------------------------------------------------------------


@router.get("/{session_id}/events")
async def handle_session_events(
    session_id: str,
    request: Request,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    """Stream-to-SSE bridge with Last-Event-ID resume support."""
    redis = request.app.state.redis
    if redis is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis not configured.")

    try:
        generator = bridge_stream_to_sse(redis, session_id, last_event_id=last_event_id)
        return EventSourceResponse(generator)
    except StreamGoneError:
        raise HTTPException(status.HTTP_410_GONE, detail=f"Stream for session '{session_id}' expired.") from None


# ---------------------------------------------------------------------------
# POST /sessions/{session_id}/interrupt
# ---------------------------------------------------------------------------


@router.post("/{session_id}/interrupt")
async def handle_interrupt_session(session_id: str, execution: ExecutionMgr) -> dict:
    """Interrupt a running session."""
    try:
        interrupted = execution.interrupt_session(session_id)
    except NoActiveSessionError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No active session '{session_id}'.") from None

    return {"session_id": session_id, "interrupted": interrupted}


# ---------------------------------------------------------------------------
# POST /sessions/{session_id}/steer
# ---------------------------------------------------------------------------


@router.post("/{session_id}/steer")
async def handle_steer_session(session_id: str, body: SteerRequest, execution: ExecutionMgr) -> dict:
    """Send steering input to a running session."""
    text_parts = [p.text for p in body.input if p.text]
    steering_text = "\n".join(text_parts) if text_parts else ""

    try:
        execution.steer_session(session_id, steering_text)
    except NoActiveSessionError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No active session '{session_id}'.") from None
    except SessionContextNotReadyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except SteeringTextRequiredError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None

    return {"session_id": session_id, "steered": True}
