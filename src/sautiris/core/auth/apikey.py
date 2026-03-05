"""API key authentication provider."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.auth.base import AuthProvider, AuthUser


class APIKeyAuthProvider(AuthProvider):
    """Header-based API key lookup against the database."""

    def __init__(self, header_name: str = "X-API-Key", session_factory: object | None = None):
        self.header_name = header_name
        self._session_factory = session_factory

    async def authenticate(self, request: Request) -> AuthUser:
        api_key = request.headers.get(self.header_name)
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Missing {self.header_name} header",
            )

        if self._session_factory is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API key auth not configured",
            )

        from sautiris.models.pacs import PACSConnection  # noqa: PLC0415

        async with self._session_factory() as session:  # type: ignore[operator]
            assert isinstance(session, AsyncSession)
            stmt = select(PACSConnection).where(PACSConnection.ae_title == api_key)
            result = await session.execute(stmt)
            _row = result.scalar_one_or_none()

        if _row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        return AuthUser(
            user_id=uuid.UUID(int=0),
            username="api-key-user",
            tenant_id=_row.tenant_id,
            roles=["service"],
            permissions=["read", "write"],
        )

    async def get_current_user(self, request: Request) -> AuthUser:
        return await self.authenticate(request)

    async def check_permission(self, user: AuthUser, permission: str) -> bool:
        return permission in user.permissions
