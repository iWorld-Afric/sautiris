"""Multi-tenancy support: ContextVar store and FastAPI dependency.

The ``TenantMiddleware`` has been **removed** (issue #1).  Tenant ID is now
sourced exclusively from the authenticated user's JWT claim — the ``X-Tenant-ID``
header is no longer trusted.

The ContextVar (``_tenant_ctx``) is still set by the ``get_current_user``
dependency in ``api/deps.py`` so that repositories and services that call
``get_current_tenant_id()`` continue to work transparently.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

import structlog

logger = structlog.get_logger(__name__)

_tenant_ctx: ContextVar[uuid.UUID | None] = ContextVar("tenant_id", default=None)

DEFAULT_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_tenant_id() -> uuid.UUID:
    """Return the current tenant ID from context, falling back to the default.

    This is set automatically by the ``get_current_user`` dependency when a
    user successfully authenticates.  Tests set it via the ``_set_tenant``
    autouse fixture.
    """
    tenant_id = _tenant_ctx.get()
    if tenant_id is None:
        logger.warning(
            "tenancy.default_fallback",
            msg="Tenant ID not set in context — falling back to DEFAULT_TENANT",
        )
        return DEFAULT_TENANT
    return tenant_id


def set_current_tenant_id(tenant_id: uuid.UUID) -> None:
    """Set the current tenant ID in context."""
    _tenant_ctx.set(tenant_id)
