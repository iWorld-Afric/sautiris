"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sautiris.core.auth.base import AuthProvider, AuthUser

if TYPE_CHECKING:
    from fastapi import Request

_session_factory: async_sessionmaker[AsyncSession] | None = None
_auth_provider: AuthProvider | None = None


def set_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    global _session_factory  # noqa: PLW0603
    _session_factory = factory


def set_auth_provider(provider: AuthProvider) -> None:
    global _auth_provider  # noqa: PLW0603
    _auth_provider = provider


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    assert _session_factory is not None, "Session factory not configured"
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(request: Request) -> AuthUser:
    """Dependency that returns the current authenticated user."""
    assert _auth_provider is not None, "Auth provider not configured"
    return await _auth_provider.get_current_user(request)


def require_permission(permission: str):  # type: ignore[no-untyped-def]  # noqa: ANN201
    """Return a FastAPI dependency that enforces *permission*."""
    from fastapi import Depends, HTTPException

    from sautiris.core.permissions import Permission, has_permission

    async def _check(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not has_permission(user.roles, Permission(permission)):
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission: {permission}",
            )
        return user

    return _check
