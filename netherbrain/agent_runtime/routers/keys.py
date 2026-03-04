"""API key management endpoints (RPC-style).

Users manage their own keys; admins can manage any user's keys.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from netherbrain.agent_runtime.deps import CurrentUser, DbSession
from netherbrain.agent_runtime.managers.users import (
    KeyNotFoundError,
    UserNotFoundError,
    create_api_key,
    list_api_keys,
    revoke_api_key,
)
from netherbrain.agent_runtime.models.api import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyResponse

router = APIRouter(prefix="/keys", tags=["keys"])


@router.post("/create", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def handle_create_key(body: ApiKeyCreate, db: DbSession, auth: CurrentUser) -> dict:
    # Determine target user.
    target_user_id = body.user_id or auth.user_id
    if target_user_id != auth.user_id and not auth.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cannot create keys for other users.")

    try:
        api_key_row, raw_key = await create_api_key(
            db,
            user_id=target_user_id,
            name=body.name,
            expires_in_days=body.expires_in_days,
        )
    except UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"User '{target_user_id}' not found.") from None

    return ApiKeyCreateResponse(
        key_id=api_key_row.key_id,
        key=raw_key,
        name=api_key_row.name,
    ).model_dump()


@router.get("/list", response_model=list[ApiKeyResponse])
async def handle_list_keys(
    db: DbSession,
    auth: CurrentUser,
    user_id: str | None = Query(None),
) -> list:
    # Non-admin can only list own keys.
    if not auth.is_admin:
        return await list_api_keys(db, user_id=auth.user_id)

    # Admin can filter by user_id or list all.
    return await list_api_keys(db, user_id=user_id)


@router.post("/{key_id}/revoke", response_model=ApiKeyResponse)
async def handle_revoke_key(key_id: str, db: DbSession, auth: CurrentUser) -> object:
    try:
        return await revoke_api_key(
            db,
            key_id,
            caller_user_id=auth.user_id,
            caller_is_admin=auth.is_admin,
        )
    except KeyNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"API key '{key_id}' not found.") from None
