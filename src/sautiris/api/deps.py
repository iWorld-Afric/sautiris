"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any, cast

import structlog
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.auth.base import AuthProvider, AuthUser
from sautiris.core.events import EventBus
from sautiris.core.tenancy import set_current_tenant_id

logger = structlog.get_logger(__name__)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session from app.state."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                logger.error("db.rollback_failed", exc_info=True)
            raise


async def get_current_user(request: Request) -> AuthUser:
    """Dependency that returns the current authenticated user.

    As a side-effect, sets the tenant ContextVar from the JWT claim so that
    repositories and services that call ``get_current_tenant_id()`` receive
    the correct tenant without trusting the ``X-Tenant-ID`` header.
    """
    auth_provider: AuthProvider = request.app.state.auth_provider
    user = await auth_provider.get_current_user(request)
    # Issue #1: ContextVar is set from JWT only — never from request header
    set_current_tenant_id(user.tenant_id)

    # SEC-1: Reject X-Tenant-ID header when it doesn't match the JWT tenant.
    # A mismatch signals either an attack (tenant spoofing) or misconfiguration.
    header_tenant = request.headers.get("X-Tenant-ID")
    if header_tenant is not None and header_tenant != str(user.tenant_id):
        logger.warning(
            "auth.tenant_id_mismatch",
            header_tenant_id=header_tenant,
            jwt_tenant_id=str(user.tenant_id),
            user_id=str(user.user_id),
        )
        raise HTTPException(
            status_code=403,
            detail="X-Tenant-ID header does not match authenticated tenant",
        )

    # FIX-2: Write user to request.state so AuditMiddleware can read it
    request.state.user = user
    return user


async def get_tenant_id(user: AuthUser = Depends(get_current_user)) -> uuid.UUID:
    """Return the tenant UUID for the current authenticated user.

    Inject this dependency on any route that needs to pass tenant_id explicitly
    to a repository or service, e.g.:
        tenant_id: uuid.UUID = Depends(get_tenant_id)
    """
    return user.tenant_id


async def get_event_bus(request: Request) -> EventBus:
    """Return the per-app EventBus instance stored on app.state."""
    return cast(EventBus, request.app.state.event_bus)


def require_permission(permission: str) -> Callable[..., Coroutine[Any, Any, AuthUser]]:
    """Return a FastAPI dependency that enforces *permission*."""
    from sautiris.core.permissions import Permission, has_permission  # noqa: PLC0415

    async def _check(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        # SEC-3: Check both role-based AND explicit permissions.
        # API key users have permissions populated directly (not via roles),
        # so the roles-only check would always reject them.
        if (
            not has_permission(user.roles, Permission(permission))
            and permission not in user.permissions
        ):
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions",
            )
        return user

    return _check
