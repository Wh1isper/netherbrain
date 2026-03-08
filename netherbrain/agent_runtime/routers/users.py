"""User management endpoints (admin only, RPC-style).

Thin HTTP adapter -- delegates all business logic to the users manager.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from netherbrain.agent_runtime.deps import AdminUser, DbSession
from netherbrain.agent_runtime.managers.users import (
    CannotDeactivateSelfError,
    DuplicateUserError,
    UserNotFoundError,
    create_user,
    deactivate_user,
    get_user,
    list_users,
    reset_password,
    update_user,
)
from netherbrain.agent_runtime.models.api import (
    ResetPasswordResponse,
    UserCreate,
    UserCreateResponse,
    UserResponse,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/create", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
async def handle_create_user(body: UserCreate, db: DbSession, admin: AdminUser) -> dict:
    try:
        user, raw_password = await create_user(
            db,
            user_id=body.user_id,
            display_name=body.display_name,
            role=body.role,
        )
    except DuplicateUserError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"User '{body.user_id}' already exists.") from None

    return {
        "user": UserResponse.model_validate(user),
        "password": raw_password,
    }


@router.get("/list", response_model=list[UserResponse])
async def handle_list_users(db: DbSession, admin: AdminUser) -> list:
    return await list_users(db)


@router.get("/{user_id}/get", response_model=UserResponse)
async def handle_get_user(user_id: str, db: DbSession, admin: AdminUser) -> object:
    try:
        return await get_user(db, user_id)
    except UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found.") from None


@router.post("/{user_id}/update", response_model=UserResponse)
async def handle_update_user(user_id: str, body: UserUpdate, db: DbSession, admin: AdminUser) -> object:
    try:
        return await update_user(
            db,
            user_id,
            display_name=body.display_name,
            role=body.role,
            is_active=body.is_active,
        )
    except UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found.") from None


@router.post("/{user_id}/deactivate", response_model=UserResponse)
async def handle_deactivate_user(user_id: str, db: DbSession, admin: AdminUser) -> object:
    try:
        return await deactivate_user(db, user_id, caller_user_id=admin.user_id)
    except UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found.") from None
    except CannotDeactivateSelfError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Cannot deactivate your own account.") from None


@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
async def handle_reset_password(user_id: str, db: DbSession, admin: AdminUser) -> dict:
    """Admin-initiated password reset. Returns a new random password."""
    try:
        new_password = await reset_password(db, user_id=user_id)
    except UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found.") from None

    return {"password": new_password}
