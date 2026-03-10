"""Global error handler middleware — sanitized 500 responses with correlation IDs."""

from __future__ import annotations

import uuid

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a sanitized 500 response with a correlation ID for traceability.

    The real exception is logged server-side (with full traceback).
    Clients never see internal stack traces or error messages.
    """
    correlation_id = str(uuid.uuid4())
    logger.error(
        "unhandled_exception",
        correlation_id=correlation_id,
        method=request.method,
        path=request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred. Please try again later.",
            "correlation_id": correlation_id,
        },
        headers={"X-Correlation-ID": correlation_id},
    )
