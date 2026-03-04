"""User and API key management.

Module-level async functions following the stateless CRUD pattern.
All functions accept ``db: AsyncSession`` as first parameter.
Raise domain exceptions, never HTTP exceptions.
"""

from __future__ import annotations

import hashlib
import secrets
import string
import warnings
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import ApiKey, User
from netherbrain.agent_runtime.models.enums import UserRole

# -- Domain exceptions -------------------------------------------------------


class UserNotFoundError(LookupError):
    """Raised when a user is not found."""


class DuplicateUserError(ValueError):
    """Raised when user_id already exists."""


class KeyNotFoundError(LookupError):
    """Raised when an API key is not found."""


class CannotDeactivateSelfError(ValueError):
    """Raised when admin tries to deactivate themselves."""


class InvalidPasswordError(ValueError):
    """Raised when the provided password is incorrect."""


class NoPasswordSetError(ValueError):
    """Raised when user has no password set (key-only account)."""


# -- Password helpers --------------------------------------------------------

_PASSWORD_LENGTH = 16
_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def _generate_password() -> str:
    """Generate a random password (server-generated, shared out of band)."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH))


def _hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# -- JWT helpers -------------------------------------------------------------

_JWT_ALGORITHM = "HS256"

# key_id used in AuthContext for JWT-authenticated requests.
JWT_KEY_ID = "jwt"


def create_jwt(user_id: str, role: str, *, secret: str, expiry_days: int) -> str:
    """Create a signed JWT token."""
    now = datetime.now(UTC)
    payload = {
        "user_id": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=expiry_days)).timestamp()),
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=jwt.warnings.InsecureKeyLengthWarning)  # type: ignore[attr-defined]
        return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)


def verify_jwt(token: str, *, secret: str) -> dict | None:
    """Verify and decode a JWT token.

    Returns the payload dict on success, None on any failure.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=jwt.warnings.InsecureKeyLengthWarning)  # type: ignore[attr-defined]
            return jwt.decode(token, secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# -- Key generation helpers --------------------------------------------------

_KEY_ID_BYTES = 4  # 4 bytes -> 8 hex chars
_KEY_SECRET_BYTES = 24  # 24 bytes -> 32 base64url chars


def _generate_key_id() -> str:
    """Generate a short random key identifier."""
    return secrets.token_hex(_KEY_ID_BYTES)


def _generate_raw_key(key_id: str) -> str:
    """Generate a full API key: ``nb_{key_id}_{secret}``."""
    secret = secrets.token_urlsafe(_KEY_SECRET_BYTES)
    return f"nb_{key_id}_{secret}"


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of a raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


# -- User CRUD ---------------------------------------------------------------


async def create_user(
    db: AsyncSession,
    *,
    user_id: str,
    display_name: str,
    role: UserRole = UserRole.USER,
    password: str | None = None,
) -> tuple[User, str, str]:
    """Create a user with a password and an initial API key.

    If ``password`` is not provided, a random one is generated.
    Returns (user_row, raw_password, raw_api_key).  Both secrets are only
    available here -- they are never stored in plaintext.
    Raises ``DuplicateUserError`` if user_id already exists.
    """
    existing = await db.get(User, user_id)
    if existing is not None:
        raise DuplicateUserError(user_id)

    raw_password = password or _generate_password()
    user = User(
        user_id=user_id,
        display_name=display_name,
        password_hash=_hash_password(raw_password),
        role=role,
        must_change_password=True,
    )
    db.add(user)
    await db.flush()  # Ensure user row exists before FK reference.

    # Generate initial API key.
    raw_key, api_key_row = _make_api_key(user_id=user_id, name="initial")
    db.add(api_key_row)

    await db.commit()
    await db.refresh(user)
    await db.refresh(api_key_row)

    return user, raw_password, raw_key


async def list_users(db: AsyncSession) -> list[User]:
    """List all users, newest first."""
    stmt = select(User).order_by(User.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_user(db: AsyncSession, user_id: str) -> User:
    """Get a user by ID.  Raises ``UserNotFoundError`` if missing."""
    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)
    return user


async def update_user(
    db: AsyncSession,
    user_id: str,
    *,
    display_name: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
) -> User:
    """Update user fields.  Raises ``UserNotFoundError`` if missing."""
    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)

    if display_name is not None:
        user.display_name = display_name
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active

    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(
    db: AsyncSession,
    *,
    user_id: str,
    password: str,
) -> User:
    """Authenticate a user by user_id and password.

    Raises ``UserNotFoundError`` if user doesn't exist.
    Raises ``NoPasswordSetError`` if user has no password (key-only).
    Raises ``InvalidPasswordError`` if password is wrong.
    Returns the user row on success.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)

    if not user.is_active:
        raise UserNotFoundError(user_id)  # Treat deactivated as not found.

    if user.password_hash is None:
        raise NoPasswordSetError(user_id)

    if not _verify_password(password, user.password_hash):
        raise InvalidPasswordError(user_id)

    return user


async def change_password(
    db: AsyncSession,
    *,
    user_id: str,
    old_password: str,
    new_password: str,
) -> None:
    """Self-service password change.

    Raises ``UserNotFoundError`` if user doesn't exist.
    Raises ``InvalidPasswordError`` if old_password is wrong.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)

    if user.password_hash is None or not _verify_password(old_password, user.password_hash):
        raise InvalidPasswordError(user_id)

    user.password_hash = _hash_password(new_password)
    user.must_change_password = False
    await db.commit()


async def reset_password(
    db: AsyncSession,
    *,
    user_id: str,
) -> str:
    """Admin-initiated password reset.  Generates a new random password.

    Returns the new plaintext password (shown once).
    Raises ``UserNotFoundError`` if user doesn't exist.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)

    raw_password = _generate_password()
    user.password_hash = _hash_password(raw_password)
    user.must_change_password = True
    await db.commit()
    return raw_password


async def deactivate_user(
    db: AsyncSession,
    user_id: str,
    *,
    caller_user_id: str,
) -> User:
    """Soft-delete a user by setting ``is_active`` to ``False``.

    All API keys are immediately invalidated at the auth layer because
    the middleware checks ``user.is_active`` on every request.

    Raises ``CannotDeactivateSelfError`` if caller tries to deactivate themselves.
    Raises ``UserNotFoundError`` if user doesn't exist.
    """
    if user_id == caller_user_id:
        raise CannotDeactivateSelfError(user_id)

    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)

    user.is_active = False
    await db.commit()
    await db.refresh(user)
    return user


# -- Bootstrap ---------------------------------------------------------------


async def bootstrap_admin(db: AsyncSession, *, password: str) -> str | None:
    """Create bootstrap admin user if no users exist.

    Uses the provided password (typically ``NETHER_AUTH_TOKEN``) so the
    operator does not need to dig through logs.
    Returns the raw API key if admin was created, None otherwise.
    """
    stmt = select(User).limit(1)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        return None  # Users exist, skip bootstrap.

    from netherbrain.agent_runtime.middleware import BOOTSTRAP_ADMIN_ID

    logger.info("No users found -- creating bootstrap admin user '{}'", BOOTSTRAP_ADMIN_ID)

    _, _raw_password, raw_key = await create_user(
        db,
        user_id=BOOTSTRAP_ADMIN_ID,
        display_name="Admin",
        role=UserRole.ADMIN,
        password=password,
    )

    logger.info("Bootstrap admin created. Login with user='{}', password=NETHER_AUTH_TOKEN", BOOTSTRAP_ADMIN_ID)
    logger.info("Bootstrap admin API key: {}", raw_key)
    return raw_key


# -- API Key CRUD ------------------------------------------------------------


def _make_api_key(*, user_id: str, name: str, expires_at: datetime | None = None) -> tuple[str, ApiKey]:
    """Create an API key row and return (raw_key, orm_row)."""
    key_id = _generate_key_id()
    raw_key = _generate_raw_key(key_id)
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:8]

    row = ApiKey(
        key_id=key_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        user_id=user_id,
        name=name,
        expires_at=expires_at,
    )
    return raw_key, row


async def create_api_key(
    db: AsyncSession,
    *,
    user_id: str,
    name: str,
    expires_in_days: int | None = None,
) -> tuple[ApiKey, str]:
    """Create an API key for a user.

    Returns (api_key_row, raw_key).  The raw key is only available here.
    Raises ``UserNotFoundError`` if user doesn't exist.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)

    expires_at = None
    if expires_in_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

    raw_key, api_key_row = _make_api_key(
        user_id=user_id,
        name=name,
        expires_at=expires_at,
    )
    db.add(api_key_row)
    await db.commit()
    await db.refresh(api_key_row)

    return api_key_row, raw_key


async def list_api_keys(
    db: AsyncSession,
    *,
    user_id: str | None = None,
) -> list[ApiKey]:
    """List API keys, optionally filtered by user.  Newest first."""
    stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
    if user_id is not None:
        stmt = stmt.where(ApiKey.user_id == user_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def revoke_api_key(
    db: AsyncSession,
    key_id: str,
    *,
    caller_user_id: str,
    caller_is_admin: bool,
) -> ApiKey:
    """Revoke an API key.  Users can revoke own keys; admins can revoke any.

    Raises ``KeyNotFoundError`` if key doesn't exist or caller lacks access.
    """
    api_key = await db.get(ApiKey, key_id)
    if api_key is None:
        raise KeyNotFoundError(key_id)

    # Non-admin can only revoke own keys.
    if not caller_is_admin and api_key.user_id != caller_user_id:
        raise KeyNotFoundError(key_id)  # 404, not 403 (avoid leaking existence).

    api_key.is_active = False
    await db.commit()
    await db.refresh(api_key)
    return api_key
