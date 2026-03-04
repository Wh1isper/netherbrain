"""Auth endpoints (RPC-style).

Handles login, identity, and password management.
Login endpoint is unauthenticated; all others require a valid token.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from netherbrain.agent_runtime.deps import CurrentUser, DbSession
from netherbrain.agent_runtime.managers.users import (
    InvalidPasswordError,
    NoPasswordSetError,
    UserNotFoundError,
    authenticate_user,
    change_password,
    create_jwt,
    get_user,
)
from netherbrain.agent_runtime.models.api import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def handle_login(body: LoginRequest, request: Request, db: DbSession) -> dict:
    """Authenticate with user_id + password, return JWT."""
    jwt_secret: str | None = getattr(request.app.state, "jwt_secret", None)
    jwt_expiry_days: int = getattr(request.app.state, "jwt_expiry_days", 7)

    if jwt_secret is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT not configured.",
        )

    try:
        user = await authenticate_user(db, user_id=body.user_id, password=body.password)
    except (UserNotFoundError, InvalidPasswordError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.") from None
    except NoPasswordSetError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="This account does not support password login.",
        ) from None

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account deactivated.") from None

    token = create_jwt(
        user.user_id,
        user.role,
        secret=jwt_secret,
        expiry_days=jwt_expiry_days,
    )

    return {
        "token": token,
        "user": UserResponse.model_validate(user),
    }


@router.get("/me", response_model=UserResponse)
async def handle_me(auth: CurrentUser, db: DbSession) -> object:
    """Return the authenticated user's profile."""
    try:
        return await get_user(db, auth.user_id)
    except UserNotFoundError:
        # Root token user may not exist in DB yet.
        return UserResponse(
            user_id=auth.user_id,
            display_name=auth.user_id,
            role=auth.role,
            is_active=True,
            must_change_password=False,
            created_at=None,  # type: ignore[arg-type]
            updated_at=None,  # type: ignore[arg-type]
        )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def handle_change_password(body: ChangePasswordRequest, auth: CurrentUser, db: DbSession) -> None:
    """Self-service password change for the authenticated user."""
    try:
        await change_password(
            db,
            user_id=auth.user_id,
            old_password=body.old_password,
            new_password=body.new_password,
        )
    except UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.") from None
    except InvalidPasswordError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect.") from None
