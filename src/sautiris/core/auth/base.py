"""Abstract base for authentication providers."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from fastapi import Request

from sautiris.core.tenancy import DEFAULT_TENANT


@dataclass(frozen=True)
class AuthUser:
    """Authenticated user identity.

    ``roles`` and ``permissions`` are immutable tuples to prevent accidental
    mutation of the frozen dataclass through list mutation (HIGH-1 fix).
    Callers may pass ``list[str]``; ``__post_init__`` coerces them to tuples.
    """

    user_id: uuid.UUID
    username: str
    email: str = ""
    # MEDIUM-14: use DEFAULT_TENANT constant instead of duplicating UUID(int=1)
    tenant_id: uuid.UUID = field(default_factory=lambda: DEFAULT_TENANT)
    roles: tuple[str, ...] = field(default_factory=tuple)
    permissions: tuple[str, ...] = field(default_factory=tuple)
    name: str = ""

    def __post_init__(self) -> None:
        """Coerce list roles/permissions to tuples for true immutability."""
        # object.__setattr__ required because dataclass is frozen=True
        if not isinstance(self.roles, tuple):
            object.__setattr__(self, "roles", tuple(self.roles))
        if not isinstance(self.permissions, tuple):
            object.__setattr__(self, "permissions", tuple(self.permissions))


class AuthProvider(ABC):
    """Abstract authentication provider."""

    @abstractmethod
    async def authenticate(self, request: Request) -> AuthUser:
        """Extract and validate credentials from the request, returning AuthUser."""

    @abstractmethod
    async def get_current_user(self, request: Request) -> AuthUser:
        """Convenience wrapper around authenticate for dependency injection."""

    @abstractmethod
    async def check_permission(self, user: AuthUser, permission: str) -> bool:
        """Check whether user has the given permission."""
