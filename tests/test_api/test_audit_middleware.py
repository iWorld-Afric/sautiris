"""Tests for AuditMiddleware — PHI route detection, correlation ID sanitization,
fire-and-forget audit task creation, and warning paths.

GAP-1: AuditMiddleware had ZERO tests.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from sautiris.api.middleware.audit_middleware import (
    _is_phi_route,
    _log_phi_access,
    _sanitize_correlation_id,
)

# ---------------------------------------------------------------------------
# Pure function tests — no HTTP needed
# ---------------------------------------------------------------------------


class TestIsPhiRoute:
    """Unit tests for _is_phi_route predicate."""

    def test_orders_prefix_is_phi(self) -> None:
        assert _is_phi_route("/api/v1/orders") is True

    def test_orders_with_id_is_phi(self) -> None:
        assert _is_phi_route("/api/v1/orders/abc-123") is True

    def test_reports_is_phi(self) -> None:
        assert _is_phi_route("/api/v1/reports") is True

    def test_patients_is_phi(self) -> None:
        assert _is_phi_route("/api/v1/patients") is True

    def test_worklist_is_phi(self) -> None:
        assert _is_phi_route("/api/v1/worklist") is True

    def test_health_not_phi(self) -> None:
        assert _is_phi_route("/api/v1/health") is False

    def test_alerts_not_phi(self) -> None:
        assert _is_phi_route("/api/v1/alerts") is False

    def test_root_not_phi(self) -> None:
        assert _is_phi_route("/") is False


class TestSanitizeCorrelationId:
    """Unit tests for _sanitize_correlation_id."""

    def test_valid_alphanumeric_preserved(self) -> None:
        cid = "abc123"
        assert _sanitize_correlation_id(cid) == cid

    def test_valid_with_dashes_preserved(self) -> None:
        cid = "my-request-id-001"
        assert _sanitize_correlation_id(cid) == cid

    def test_valid_uuid_preserved(self) -> None:
        cid = str(uuid.uuid4()).replace("-", "")[:32]
        # UUID hex without dashes — valid alphanumeric
        assert _sanitize_correlation_id(cid) == cid

    def test_too_long_replaced_with_uuid(self) -> None:
        cid = "a" * 65  # exceeds 64 char limit
        result = _sanitize_correlation_id(cid)
        assert result != cid
        uuid.UUID(result)  # result must be a valid UUID

    def test_empty_string_replaced_with_uuid(self) -> None:
        result = _sanitize_correlation_id("")
        uuid.UUID(result)

    def test_injection_chars_rejected(self) -> None:
        for bad in ("../../etc/passwd", "<script>", "'; DROP TABLE--", "\n\r"):
            result = _sanitize_correlation_id(bad)
            assert result != bad
            uuid.UUID(result)  # replaced with UUID


# ---------------------------------------------------------------------------
# Integration tests via ASGI transport
# ---------------------------------------------------------------------------


def _make_audit_app(phi_status: int = 200) -> FastAPI:
    """Minimal app with AuditMiddleware and one PHI + one non-PHI route."""
    from sautiris.api.middleware.audit_middleware import AuditMiddleware

    app = FastAPI()
    app.add_middleware(AuditMiddleware)

    @app.get("/api/v1/orders/")
    async def phi_endpoint() -> JSONResponse:
        return JSONResponse({"ok": True}, status_code=phi_status)

    @app.get("/api/v1/health")
    async def health_endpoint() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return app


class TestAuditMiddlewarePHIDetection:
    """PHI route detection — correlation ID header is the observable effect."""

    async def test_phi_route_gets_correlation_id_header(self) -> None:
        """PHI route responses include X-Correlation-ID regardless of auth state."""
        app = _make_audit_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/orders/")
        assert "x-correlation-id" in resp.headers

    async def test_non_phi_route_skipped_no_header(self) -> None:
        """Non-PHI route passes through — middleware does NOT add X-Correlation-ID."""
        app = _make_audit_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/health")
        assert "x-correlation-id" not in resp.headers


class TestCorrelationIdHandling:
    """Correlation ID sanitization and propagation."""

    async def test_valid_correlation_id_echoed_back(self) -> None:
        """A valid X-Correlation-ID header is preserved in the response."""
        app = _make_audit_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/orders/", headers={"X-Correlation-ID": "valid-id-abc123"})
        assert resp.headers["x-correlation-id"] == "valid-id-abc123"

    async def test_invalid_correlation_id_is_replaced(self) -> None:
        """Injection-like X-Correlation-ID is replaced with a safe UUID."""
        app = _make_audit_app()
        malicious = "../../etc/INJECTION<script>"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/orders/", headers={"X-Correlation-ID": malicious})
        returned = resp.headers["x-correlation-id"]
        assert returned != malicious
        uuid.UUID(returned)  # must be a valid UUID

    async def test_missing_correlation_id_generates_uuid(self) -> None:
        """When no X-Correlation-ID is provided, a UUID is auto-generated."""
        app = _make_audit_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/orders/")
        uuid.UUID(resp.headers["x-correlation-id"])  # must be a valid UUID


class TestFireAndForgetAuditTask:
    """Verify asyncio.create_task is (or is not) called based on response status."""

    async def test_audit_task_created_on_success(self) -> None:
        """Status 200 → asyncio.create_task is called with audit: name prefix."""
        app = _make_audit_app(phi_status=200)
        captured: list[str] = []

        def _fake_create_task(coro: object, *, name: str = "") -> MagicMock:
            # Consume the coroutine to avoid "never awaited" RuntimeWarning
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[union-attr]
            captured.append(name)
            return MagicMock()

        with patch("asyncio.create_task", side_effect=_fake_create_task):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                await c.get("/api/v1/orders/")

        assert len(captured) == 1
        assert captured[0].startswith("audit:")

    async def test_no_audit_task_on_4xx_response(self) -> None:
        """Status 403 → asyncio.create_task is NOT called (no PHI access to log)."""
        app = _make_audit_app(phi_status=403)

        with patch("asyncio.create_task") as mock_task:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.get("/api/v1/orders/")

        assert resp.status_code == 403
        mock_task.assert_not_called()


class TestLogPhiAccessWarningPaths:
    """Direct tests for _log_phi_access warning/early-return paths."""

    async def test_warning_when_no_session_factory(self) -> None:
        """_log_phi_access logs a warning and returns when session_factory is absent."""

        class _FakeState:
            pass  # no session_factory attribute

        class _FakeApp:
            state = _FakeState()

        request = MagicMock()
        request.app = _FakeApp()
        request.url.path = "/api/v1/orders"

        response = MagicMock()
        response.status_code = 200

        # Should not raise; logs a warning and returns cleanly
        await _log_phi_access(request, response, "test-cid")

    async def test_warning_when_no_authenticated_user(self) -> None:
        """_log_phi_access logs a warning and returns when request.state.user is None."""
        mock_factory = AsyncMock()

        class _FakeState:
            session_factory = mock_factory
            # no 'user' attribute → getattr(state, "user", None) returns None

        class _FakeApp:
            state = _FakeState()

        request = MagicMock()
        request.app = _FakeApp()
        request.url.path = "/api/v1/orders"
        # Make request.state not have 'user':
        del_state = MagicMock(spec=[])  # spec=[] means no attributes
        request.state = del_state

        response = MagicMock()
        response.status_code = 200

        # Returns early without calling session_factory
        await _log_phi_access(request, response, "test-cid")
        mock_factory.assert_not_called()


# ---------------------------------------------------------------------------
# GAP-I5: _log_phi_access happy path — AuditLogger.log is called with correct
#         resource_type when a valid authenticated user is present.
# ---------------------------------------------------------------------------


class TestLogPhiAccessHappyPath:
    """_log_phi_access with a fully configured app state writes an audit log entry."""

    async def test_phi_access_calls_audit_logger_log(self) -> None:
        """When session_factory and user are configured, AuditLogger.log is called."""
        import uuid
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, MagicMock, patch

        from sautiris.core.auth.base import AuthUser

        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user = AuthUser(
            user_id=uuid.uuid4(),
            username="radiologist",
            email="rad@example.com",
            tenant_id=tenant_id,
            roles=("radiologist",),
            permissions=("report:read",),
            name="Radiologist",
        )

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        # factory must be a stand-alone callable (not a method), otherwise
        # Python will pass `self` as the first argument when it is accessed
        # as a class attribute.
        @asynccontextmanager
        async def _standalone_factory():  # type: ignore[misc]
            yield mock_session

        # Build a fake app.state with session_factory
        class _FakeState:
            session_factory = staticmethod(_standalone_factory)

        class _FakeApp:
            state = _FakeState()

        # Build a fake request with user in state
        request = MagicMock()
        request.app = _FakeApp()
        request.url.path = "/api/v1/orders"
        request.method = "GET"
        request.headers.get = MagicMock(return_value="")
        request.client = MagicMock()
        request.client.host = "10.0.0.1"

        state = MagicMock()
        state.user = user
        request.state = state

        response = MagicMock()
        response.status_code = 200

        mock_audit_instance = AsyncMock()

        # AuditLogger is imported inside _log_phi_access via a local import.
        # Patch at the source module so the local import resolves to the mock.
        with patch("sautiris.core.audit.AuditLogger", return_value=mock_audit_instance):
            await _log_phi_access(request, response, "test-correlation-id")

        # AuditLogger.log must have been called once
        mock_audit_instance.log.assert_called_once()
        call_kwargs = mock_audit_instance.log.call_args
        # resource_type for /api/v1/orders → "ORDERS"
        actual_resource_type = call_kwargs.kwargs.get("resource_type", "")
        assert actual_resource_type == "ORDERS", (
            f"Expected resource_type='ORDERS', got {actual_resource_type!r}"
        )

    async def test_phi_access_resource_type_reports(self) -> None:
        """_resource_type_from_path returns 'REPORTS' for /api/v1/reports/* paths."""
        from sautiris.api.middleware.audit_middleware import _resource_type_from_path

        assert _resource_type_from_path("/api/v1/reports") == "REPORTS"
        assert _resource_type_from_path("/api/v1/reports/abc-123") == "REPORTS"

    async def test_phi_access_resource_type_orders(self) -> None:
        """_resource_type_from_path returns 'ORDERS' for /api/v1/orders/* paths."""
        from sautiris.api.middleware.audit_middleware import _resource_type_from_path

        assert _resource_type_from_path("/api/v1/orders") == "ORDERS"
        assert _resource_type_from_path("/api/v1/orders/some-uuid") == "ORDERS"

    async def test_phi_access_resource_type_worklist(self) -> None:
        """_resource_type_from_path returns 'WORKLIST' for /api/v1/worklist paths."""
        from sautiris.api.middleware.audit_middleware import _resource_type_from_path

        assert _resource_type_from_path("/api/v1/worklist") == "WORKLIST"


# ---------------------------------------------------------------------------
# GAP-R4-1: _log_phi_access OperationalError path
# ---------------------------------------------------------------------------


class TestLogPhiAccessOperationalError:
    """_log_phi_access catches OperationalError without re-raising and logs CRITICAL."""

    def _make_request_with_user(self) -> MagicMock:
        """Return a fake request with a fully configured app.state and an authenticated user."""
        import uuid
        from contextlib import asynccontextmanager

        from sautiris.core.auth.base import AuthUser

        user = AuthUser(
            user_id=uuid.uuid4(),
            username="radiologist",
            email="rad@example.com",
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            roles=("radiologist",),
            permissions=("order:read",),
            name="Test Radiologist",
        )

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        @asynccontextmanager
        async def _standalone_factory():  # type: ignore[misc]
            yield mock_session

        class _FakeState:
            session_factory = staticmethod(_standalone_factory)

        class _FakeApp:
            state = _FakeState()

        request = MagicMock()
        request.app = _FakeApp()
        request.url.path = "/api/v1/orders"
        request.method = "GET"
        request.headers.get = MagicMock(return_value="")
        request.client = MagicMock()
        request.client.host = "10.0.0.1"

        state = MagicMock()
        state.user = user
        request.state = state
        return request

    async def test_operational_error_does_not_raise(self) -> None:
        """When AuditLogger.log raises OperationalError, _log_phi_access must not re-raise."""
        import sqlalchemy.exc

        request = self._make_request_with_user()
        response = MagicMock()
        response.status_code = 200

        # Patch AuditLogger so that .log() raises OperationalError
        mock_audit = AsyncMock()
        mock_audit.log = AsyncMock(
            side_effect=sqlalchemy.exc.OperationalError("DB gone", None, None)
        )

        with patch("sautiris.core.audit.AuditLogger", return_value=mock_audit):
            # Must complete without raising
            await _log_phi_access(request, response, "test-op-err-cid")

    async def test_operational_error_logs_critical(self) -> None:
        """When OperationalError is caught, logger.critical is called with the right key."""
        import sqlalchemy.exc

        request = self._make_request_with_user()
        response = MagicMock()
        response.status_code = 200

        mock_audit = AsyncMock()
        mock_audit.log = AsyncMock(
            side_effect=sqlalchemy.exc.OperationalError("DB gone", None, None)
        )

        with (
            patch("sautiris.core.audit.AuditLogger", return_value=mock_audit),
            patch("sautiris.api.middleware.audit_middleware.logger") as mock_logger,
        ):
            await _log_phi_access(request, response, "test-critical-cid")

        mock_logger.critical.assert_called_once()
        call_args = mock_logger.critical.call_args
        event_key = call_args[0][0] if call_args[0] else ""
        assert event_key == "audit_middleware.database_unreachable"

    async def test_generic_exception_logs_error_not_critical(self) -> None:
        """A non-OperationalError exception is caught by the generic except and logs ERROR."""
        request = self._make_request_with_user()
        response = MagicMock()
        response.status_code = 200

        mock_audit = AsyncMock()
        mock_audit.log = AsyncMock(side_effect=RuntimeError("unexpected failure"))

        with (
            patch("sautiris.core.audit.AuditLogger", return_value=mock_audit),
            patch("sautiris.api.middleware.audit_middleware.logger") as mock_logger,
        ):
            await _log_phi_access(request, response, "test-generic-cid")

        # Generic exception → logger.error (not logger.critical)
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        event_key = call_args[0][0] if call_args[0] else ""
        assert event_key == "audit_middleware.log_failed"
        mock_logger.critical.assert_not_called()
