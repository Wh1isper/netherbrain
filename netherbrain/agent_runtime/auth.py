"""Authentication context shared between middleware and dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from netherbrain.agent_runtime.models.enums import UserRole


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Identity of the authenticated caller, set by auth middleware."""

    user_id: str
    role: UserRole
    key_id: str

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN
