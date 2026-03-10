"""Audit middleware — logs all PHI route access to the audit_logs table.

Issue #22: Every request to PHI routes (orders, reports, patients, worklist)
must create an AuditLog entry with correlation_id, user identity, and outcome.
Records are append-only — no UPDATE or DELETE operations on the audit table.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import TYPE_CHECKING

import sqlalchemy.exc
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = structlog.get_logger(__name__)

# Routes whose access must be audited (prefix match)
PHI_ROUTE_PREFIXES: tuple[str, ...] = (
    "/api/v1/orders",
    "/api/v1/reports",
    "/api/v1/patients",
    "/api/v1/worklist",
)

# FIX-10: Allowlist pattern for client-provided correlation IDs
_CORRELATION_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


def _is_phi_route(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PHI_ROUTE_PREFIXES)


def _sanitize_correlation_id(value: str) -> str:
    """Return *value* if it matches the safe pattern, else generate a new UUID.

    Prevents arbitrary strings injected via X-Correlation-ID from appearing in
    audit logs.
    """
    if value and _CORRELATION_ID_RE.match(value):
        return value
    return str(uuid.uuid4())


class AuditMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that logs access to PHI routes.

    Logging happens *after* the response so we can record the HTTP status code.
    Only successful (< 400) requests are logged; auth failures are not PHI access.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not _is_phi_route(request.url.path):
            return await call_next(request)

        # FIX-10: Sanitize client-provided correlation ID before storing in audit logs
        raw_cid = request.headers.get("X-Correlation-ID", "")
        correlation_id = _sanitize_correlation_id(raw_cid)
        # Attach correlation_id to request state so handlers can reference it
        request.state.correlation_id = correlation_id

        response = await call_next(request)

        if response.status_code < 400:
            # FIX-4: Fire-and-forget — decouple audit write from the response path
            task = asyncio.create_task(
                _log_phi_access(request, response, correlation_id),
                name=f"audit:{correlation_id}",
            )
            task.add_done_callback(_log_audit_failure)

        response.headers["X-Correlation-ID"] = correlation_id
        return response


def _log_audit_failure(task: asyncio.Task[None]) -> None:
    """Callback that logs CRITICAL if the fire-and-forget audit task failed."""
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.critical(
            "audit_middleware.fire_and_forget_failed",
            task_name=task.get_name(),
            exc_info=exc,
            msg=(
                "PHI audit log write failed in background task"
                " — HIPAA audit trail may be incomplete"
            ),
        )


async def _log_phi_access(
    request: Request,
    response: Response,
    correlation_id: str,
) -> None:
    """Audit log write — runs as a background task (fire-and-forget)."""
    try:
        # Only log if app state provides a session factory (may be absent in tests)
        if not hasattr(request.app.state, "session_factory"):
            logger.warning(
                "audit_middleware.skipping_phi_log",
                path=request.url.path,
                reason="session_factory not configured in app.state",
            )
            return

        from sautiris.core.audit import AuditLogger
        from sautiris.core.auth.base import AuthUser

        user: AuthUser | None = getattr(request.state, "user", None)
        if user is None:
            logger.warning(
                "audit_middleware.skipping_phi_log",
                path=request.url.path,
                reason="no authenticated user in request.state",
            )
            return  # unauthenticated requests were already rejected before here

        factory = request.app.state.session_factory
        async with factory() as session:
            audit = AuditLogger(session)
            # Derive action from HTTP method
            method_to_action = {
                "GET": "READ",
                "POST": "CREATE",
                "PUT": "UPDATE",
                "PATCH": "UPDATE",
                "DELETE": "DELETE",
            }
            action = method_to_action.get(request.method, request.method)
            resource_type = _resource_type_from_path(request.url.path)

            await audit.log(
                user=user,
                action=action,
                resource_type=resource_type,
                ip_address=_get_client_ip(request),
                user_agent=request.headers.get("User-Agent", ""),
                correlation_id=correlation_id,
                details={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                },
            )
            await session.commit()
    except sqlalchemy.exc.OperationalError:
        # Audit failures must never break the request cycle
        logger.critical(
            "audit_middleware.database_unreachable",
            exc_info=True,
            msg="HIPAA audit log write failed — database unreachable",
        )
    except Exception:
        logger.error("audit_middleware.log_failed", exc_info=True)


def _resource_type_from_path(path: str) -> str:
    """Extract a resource type label from the URL path."""
    for prefix in PHI_ROUTE_PREFIXES:
        if path.startswith(prefix):
            return prefix.split("/")[-1].upper()
    return "UNKNOWN"


def _get_client_ip(request: Request) -> str:
    """Return the TCP-level client IP.

    FIX-3: X-Forwarded-For is NOT trusted — it can be spoofed by attackers to
    inject arbitrary IPs into HIPAA audit logs.  Only the TCP connection address
    (request.client.host) is used.  Operators who sit behind a trusted reverse
    proxy must configure their proxy to overwrite X-Forwarded-For with the real
    client IP at the network layer, not here.
    """
    if request.client:
        return request.client.host
    return ""
