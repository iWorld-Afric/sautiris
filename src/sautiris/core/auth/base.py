"""Abstract base for authentication providers."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from fastapi import Request


@dataclass(frozen=True)
class AuthUser:
    """Authenticated user identity."""

    user_id: uuid.UUID
    username: str
    email: str = ""
    tenant_id: uuid.UUID = field(default_factory=lambda: uuid.UUID(int=1))
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    name: str = ""


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
