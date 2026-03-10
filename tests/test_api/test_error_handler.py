"""Tests for the global unhandled exception handler middleware.

GAP-4: error_handler.py had zero tests — sanitized 500 responses with
correlation IDs must never leak stack traces to clients.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from sautiris.api.middleware.error_handler import unhandled_exception_handler


def _make_error_app() -> FastAPI:
    """Minimal app that exposes two routes — one that raises, one that is fine."""
    app = FastAPI()
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]

    @app.get("/boom")
    async def explode() -> None:
        raise RuntimeError("Something went terribly wrong")

    @app.get("/ok")
    async def fine() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _make_transport(app: FastAPI) -> ASGITransport:
    """ASGITransport that suppresses server-side exceptions.

    Starlette's ServerErrorMiddleware re-raises after sending the 500 response
    so that test clients can optionally detect errors.  Setting
    raise_app_exceptions=False tells httpx to ignore the re-raise and just
    return the response that was already sent.
    """
    return ASGITransport(app=app, raise_app_exceptions=False)


class TestUnhandledExceptionHandler:
    """Verify that the global exception handler sanitizes responses correctly."""

    async def test_unhandled_exception_returns_500(self) -> None:
        """Raising an exception → HTTP 500 response."""
        app = _make_error_app()
        async with AsyncClient(transport=_make_transport(app), base_url="http://test") as c:
            resp = await c.get("/boom")
        assert resp.status_code == 500

    async def test_no_stack_trace_leaked_in_response_body(self) -> None:
        """Exception message and traceback are NOT exposed to the client."""
        app = _make_error_app()
        async with AsyncClient(transport=_make_transport(app), base_url="http://test") as c:
            resp = await c.get("/boom")

        body = resp.text
        # Internal error message must not appear in response
        assert "Something went terribly wrong" not in body
        assert "RuntimeError" not in body
        assert "Traceback" not in body

    async def test_correlation_id_in_error_response_body(self) -> None:
        """Error response body contains a correlation_id field."""
        app = _make_error_app()
        async with AsyncClient(transport=_make_transport(app), base_url="http://test") as c:
            resp = await c.get("/boom")

        data = resp.json()
        assert "correlation_id" in data
        # Correlation ID must be a valid UUID
        uuid.UUID(data["correlation_id"])

    async def test_correlation_id_in_response_header(self) -> None:
        """The X-Correlation-ID header is set on error responses."""
        app = _make_error_app()
        async with AsyncClient(transport=_make_transport(app), base_url="http://test") as c:
            resp = await c.get("/boom")

        assert "x-correlation-id" in resp.headers
        uuid.UUID(resp.headers["x-correlation-id"])

    async def test_correlation_id_matches_body_and_header(self) -> None:
        """The correlation_id in the body matches the X-Correlation-ID header."""
        app = _make_error_app()
        async with AsyncClient(transport=_make_transport(app), base_url="http://test") as c:
            resp = await c.get("/boom")

        body_cid = resp.json()["correlation_id"]
        header_cid = resp.headers["x-correlation-id"]
        assert body_cid == header_cid

    async def test_generic_error_detail_message(self) -> None:
        """The 'detail' field contains a user-friendly message, not internal error."""
        app = _make_error_app()
        async with AsyncClient(transport=_make_transport(app), base_url="http://test") as c:
            resp = await c.get("/boom")

        data = resp.json()
        assert "detail" in data
        assert "internal" in data["detail"].lower() or "error" in data["detail"].lower()

    async def test_normal_routes_unaffected(self) -> None:
        """Non-raising routes work normally through the exception handler app."""
        app = _make_error_app()
        async with AsyncClient(transport=_make_transport(app), base_url="http://test") as c:
            resp = await c.get("/ok")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
