"""Multi-tenancy middleware and context."""

from __future__ import annotations

import contextlib
import uuid
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

_tenant_ctx: ContextVar[uuid.UUID | None] = ContextVar("tenant_id", default=None)

DEFAULT_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_tenant_id() -> uuid.UUID:
    """Return the current tenant ID from context, falling back to the default."""
    return _tenant_ctx.get() or DEFAULT_TENANT


def set_current_tenant_id(tenant_id: uuid.UUID) -> None:
    """Set the current tenant ID in context."""
    _tenant_ctx.set(tenant_id)


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant_id from JWT claim or request header."""

    def __init__(
        self, app: object, header_name: str = "X-Tenant-ID", jwt_claim: str = "tenant_id"
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.header_name = header_name
        self.jwt_claim = jwt_claim

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        tenant_id: uuid.UUID | None = None

        # Try header first
        header_val = request.headers.get(self.header_name)
        if header_val:
            with contextlib.suppress(ValueError):
                tenant_id = uuid.UUID(header_val)

        # Fall back to auth user (set by auth middleware/dependency)
        if tenant_id is None:
            user = getattr(request.state, "user", None)
            if user and hasattr(user, "tenant_id"):
                tenant_id = user.tenant_id

        set_current_tenant_id(tenant_id or DEFAULT_TENANT)
        response = await call_next(request)
        return response
