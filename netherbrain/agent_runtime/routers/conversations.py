"""Conversation endpoints (RPC-style).

Thin HTTP adapter -- parses request params, calls managers, translates
domain exceptions to HTTP responses.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from netherbrain.agent_runtime.deps import CurrentUser, DbSession, ExecutionMgr, SessionMgr
from netherbrain.agent_runtime.execution.resolver import (
    NoPresetError,
    ProjectConflictError,
    WorkspaceNotFoundError,
)
from netherbrain.agent_runtime.managers.conversations import (
    ConversationNotFoundError,
    get_conversation,
    list_conversations,
    update_conversation,
)
from netherbrain.agent_runtime.managers.execution import (
    ConversationBusyError,
    EmptyMailboxError,
    InputRequiredError,
    NoActiveSessionError,
    NoCommittedSessionError,
    NoDefaultPresetError,
    SessionContextNotReadyError,
    SessionNotInConversationError,
    SteeringTextRequiredError,
)
from netherbrain.agent_runtime.managers.mailbox import count_pending, query_mailbox
from netherbrain.agent_runtime.models.api import (
    ActiveSessionInfo,
    ConversationBusyResponse,
    ConversationDetailResponse,
    ConversationFireRequest,
    ConversationForkRequest,
    ConversationResponse,
    ConversationRunRequest,
    ConversationUpdate,
    ExecuteAcceptedResponse,
    LatestSessionInfo,
    MailboxMessageResponse,
    MailboxSummary,
    SessionResponse,
    SteerRequest,
)
from netherbrain.agent_runtime.models.enums import SessionStatus, SessionType, Transport
from netherbrain.agent_runtime.transport.bridge import StreamGoneError, bridge_stream_to_sse

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Shared response builder
# ---------------------------------------------------------------------------


def _launch_response(result):
    """Convert LaunchResult to HTTP response (SSE stream or 202 Accepted)."""
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
# POST /conversations/run
# ---------------------------------------------------------------------------


@router.post("/run")
async def handle_run(body: ConversationRunRequest, db: DbSession, execution: ExecutionMgr, auth: CurrentUser):
    """Main entry point. Create or continue a conversation."""
    # Ownership check for continue case.
    if body.conversation_id is not None:
        try:
            await get_conversation(db, body.conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
        except ConversationNotFoundError:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"Conversation '{body.conversation_id}' not found."
            ) from None
    try:
        result = await execution.run_conversation(
            db,
            conversation_id=body.conversation_id,
            preset_id=body.preset_id,
            input_parts=body.input,
            user_interactions=body.user_interactions,
            tool_results=body.tool_results,
            workspace_id=body.workspace_id,
            project_ids=body.project_ids,
            config_override=body.config_override,
            metadata=body.metadata,
            transport=body.transport,
            user_id=auth.user_id,
        )
    except InputRequiredError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except ConversationBusyError as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=ConversationBusyResponse(
                active_session=ActiveSessionInfo(
                    session_id=exc.active_session.session_id,
                    stream_key=exc.active_session.stream_key,
                    transport=exc.active_session.transport,
                ),
            ).model_dump(),
        )
    except (NoPresetError, WorkspaceNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except (ProjectConflictError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None

    return _launch_response(result)


# ---------------------------------------------------------------------------
# POST /conversations/{conversation_id}/fork
# ---------------------------------------------------------------------------


@router.post("/{conversation_id}/fork")
async def handle_fork(
    conversation_id: str, body: ConversationForkRequest, db: DbSession, execution: ExecutionMgr, auth: CurrentUser
):
    """Fork a new conversation from a session in this conversation."""
    # Ownership check on source conversation.
    try:
        await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None
    try:
        result = await execution.fork_conversation(
            db,
            conversation_id=conversation_id,
            preset_id=body.preset_id,
            input_parts=body.input,
            from_session_id=body.from_session_id,
            workspace_id=body.workspace_id,
            project_ids=body.project_ids,
            config_override=body.config_override,
            metadata=body.metadata,
            transport=body.transport,
            user_id=auth.user_id,
        )
    except (
        ConversationNotFoundError,
        NoCommittedSessionError,
        NoPresetError,
        WorkspaceNotFoundError,
        LookupError,
    ) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except (SessionNotInConversationError, ProjectConflictError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None

    return _launch_response(result)


# ---------------------------------------------------------------------------
# POST /conversations/{conversation_id}/interrupt
# ---------------------------------------------------------------------------


@router.post("/{conversation_id}/interrupt")
async def handle_interrupt(conversation_id: str, db: DbSession, execution: ExecutionMgr, auth: CurrentUser) -> dict:
    """Interrupt all active sessions in the conversation."""
    try:
        await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None

    interrupted = execution.interrupt_conversation(conversation_id)
    return {"conversation_id": conversation_id, "interrupted": interrupted}


# ---------------------------------------------------------------------------
# POST /conversations/{conversation_id}/steer
# ---------------------------------------------------------------------------


@router.post("/{conversation_id}/steer")
async def handle_steer(
    conversation_id: str, body: SteerRequest, db: DbSession, execution: ExecutionMgr, auth: CurrentUser
) -> dict:
    """Steer the active agent session in the conversation."""
    try:
        await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None

    text_parts = [p.text for p in body.input if p.text]
    steering_text = "\n".join(text_parts) if text_parts else ""

    try:
        session_id = execution.steer_conversation(conversation_id, steering_text)
    except NoActiveSessionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except SessionContextNotReadyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except SteeringTextRequiredError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None

    return {"conversation_id": conversation_id, "session_id": session_id, "steered": True}


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id}/events
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/events")
async def handle_events(
    conversation_id: str,
    db: DbSession,
    execution: ExecutionMgr,
    request: Request,
    auth: CurrentUser,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    """Stream-to-SSE bridge for the active agent session."""
    try:
        await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None

    try:
        active = execution.get_active_session(conversation_id)
    except NoActiveSessionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None

    if active.transport != Transport.STREAM:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Active session uses SSE transport; use the direct SSE response from run/fork.",
        )

    redis = request.app.state.redis
    if redis is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis not configured.")

    try:
        generator = bridge_stream_to_sse(redis, active.session_id, last_event_id=last_event_id)
        return EventSourceResponse(generator)
    except StreamGoneError:
        raise HTTPException(status.HTTP_410_GONE, detail=f"Stream for session '{active.session_id}' expired.") from None


# ---------------------------------------------------------------------------
# GET /conversations/list
# ---------------------------------------------------------------------------


@router.get("/list", response_model=list[ConversationResponse])
async def handle_list_conversations(
    db: DbSession,
    auth: CurrentUser,
    conversation_status: str | None = Query(None, alias="status"),
    metadata_contains: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list:
    try:
        return await list_conversations(
            db,
            user_id=None if auth.is_admin else auth.user_id,
            status=conversation_status,
            metadata_contains=metadata_contains,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id}/get
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/get", response_model=ConversationDetailResponse)
async def handle_get_conversation(
    conversation_id: str,
    db: DbSession,
    execution: ExecutionMgr,
    manager: SessionMgr,
    auth: CurrentUser,
) -> dict:
    """Get conversation with enriched session and mailbox info."""
    try:
        conv = await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None

    # Build base response from ORM row.
    result: dict = ConversationResponse.model_validate(conv).model_dump()

    # Latest committed session.
    latest_row = await manager.find_latest_committed_session(db, conversation_id)
    if latest_row is not None:
        result["latest_session"] = LatestSessionInfo(
            session_id=latest_row.session_id,
            status=SessionStatus(latest_row.status),
            session_type=SessionType(latest_row.session_type),
            project_ids=latest_row.project_ids,
            preset_id=latest_row.preset_id,
            created_at=latest_row.created_at,
        )

    # Active agent session (from in-memory registry).
    try:
        active = execution.get_active_session(conversation_id)
        result["active_session"] = ActiveSessionInfo(
            session_id=active.session_id,
            stream_key=active.stream_key,
            transport=active.transport,
        )
    except NoActiveSessionError:
        pass

    # Mailbox summary.
    pending = await count_pending(db, conversation_id=conversation_id)
    result["mailbox"] = MailboxSummary(pending_count=pending)

    return result


# ---------------------------------------------------------------------------
# POST /conversations/{conversation_id}/update
# ---------------------------------------------------------------------------


@router.post("/{conversation_id}/update", response_model=ConversationResponse)
async def handle_update_conversation(
    conversation_id: str, body: ConversationUpdate, db: DbSession, auth: CurrentUser
) -> object:
    try:
        # Verify ownership first.
        await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
        return await update_conversation(db, conversation_id, body)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id}/turns
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/turns")
async def handle_get_conversation_turns(
    conversation_id: str,
    db: DbSession,
    manager: SessionMgr,
    auth: CurrentUser,
    include_display: bool = Query(False),
) -> list[dict]:
    try:
        await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None

    return await manager.get_conversation_turns(db, conversation_id, include_display=include_display)


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id}/sessions
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/sessions", response_model=list[SessionResponse])
async def handle_list_conversation_sessions(
    conversation_id: str,
    db: DbSession,
    manager: SessionMgr,
    auth: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list:
    try:
        await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None

    return await manager.list_sessions(db, conversation_id, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# POST /conversations/{conversation_id}/fire
# ---------------------------------------------------------------------------


@router.post("/{conversation_id}/fire")
async def handle_fire(
    conversation_id: str, body: ConversationFireRequest, db: DbSession, execution: ExecutionMgr, auth: CurrentUser
):
    """Drain mailbox and launch a continuation session."""
    # Ownership check on source conversation.
    try:
        await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None
    try:
        result = await execution.fire_conversation(
            db,
            conversation_id=conversation_id,
            preset_id=body.preset_id,
            input_parts=body.input,
            user_interactions=body.user_interactions,
            tool_results=body.tool_results,
            workspace_id=body.workspace_id,
            project_ids=body.project_ids,
            config_override=body.config_override,
            transport=body.transport,
            user_id=auth.user_id,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except ConversationBusyError as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=ConversationBusyResponse(
                active_session=ActiveSessionInfo(
                    session_id=exc.active_session.session_id,
                    stream_key=exc.active_session.stream_key,
                    transport=exc.active_session.transport,
                ),
            ).model_dump(),
        )
    except (EmptyMailboxError, NoDefaultPresetError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    except (NoPresetError, WorkspaceNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except (ProjectConflictError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None

    return _launch_response(result)


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id}/mailbox
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/mailbox", response_model=list[MailboxMessageResponse])
async def handle_mailbox(
    conversation_id: str,
    db: DbSession,
    auth: CurrentUser,
    pending_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list:
    """Query mailbox messages for a conversation."""
    try:
        await get_conversation(db, conversation_id, user_id=auth.user_id, is_admin=auth.is_admin)
    except ConversationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Conversation '{conversation_id}' not found.") from None

    return await query_mailbox(
        db,
        conversation_id=conversation_id,
        pending_only=pending_only,
        limit=limit,
        offset=offset,
    )
