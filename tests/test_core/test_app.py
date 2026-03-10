"""Tests for the SautiRIS application factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI

from sautiris.app import create_ris_app
from sautiris.config import SautiRISSettings


def _make_settings(**overrides: object) -> SautiRISSettings:
    defaults = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "auth_provider": "apikey",
    }
    defaults.update(overrides)
    return SautiRISSettings(**defaults)


class TestCreateRISApp:
    """Tests for create_ris_app factory function."""

    @patch("sautiris.app.create_async_engine")
    def test_returns_fastapi_instance(self, mock_engine: MagicMock) -> None:
        app = create_ris_app(settings=_make_settings())
        assert isinstance(app, FastAPI)

    @patch("sautiris.app.create_async_engine")
    def test_app_title(self, mock_engine: MagicMock) -> None:
        app = create_ris_app(settings=_make_settings())
        assert app.title == "SautiRIS"

    @patch("sautiris.app.create_async_engine")
    def test_app_version(self, mock_engine: MagicMock) -> None:
        app = create_ris_app(settings=_make_settings())
        assert app.version == "1.0.0a2"

    @patch("sautiris.app.create_async_engine")
    def test_routes_registered(self, mock_engine: MagicMock) -> None:
        app = create_ris_app(settings=_make_settings())
        route_paths = [r.path for r in app.routes]
        assert any("/health" in p for p in route_paths)

    @patch("sautiris.app.create_async_engine")
    def test_keycloak_auth_provider(self, mock_engine: MagicMock) -> None:
        app = create_ris_app(
            settings=_make_settings(
                auth_provider="keycloak",
                keycloak_server_url="http://localhost:8080",
                keycloak_realm="test",
                keycloak_client_id="test-client",
                keycloak_jwks_url="http://localhost:8080/certs",
            )
        )
        assert isinstance(app, FastAPI)

    @patch("sautiris.app.create_async_engine")
    def test_oauth2_auth_provider(self, mock_engine: MagicMock) -> None:
        app = create_ris_app(
            settings=_make_settings(
                auth_provider="oauth2",
                oauth2_jwks_url="http://localhost/.well-known/jwks.json",
                oauth2_issuer="http://localhost",
                oauth2_audience="test-api",
            )
        )
        assert isinstance(app, FastAPI)

    @patch("sautiris.app.create_async_engine")
    def test_overrides_create_settings(self, mock_engine: MagicMock) -> None:
        app = create_ris_app(
            database_url="postgresql+asyncpg://localhost/test",
            auth_provider="apikey",
        )
        assert isinstance(app, FastAPI)

    @patch("sautiris.app.create_async_engine")
    def test_engine_created_with_correct_url(self, mock_engine: MagicMock) -> None:
        url = "postgresql+asyncpg://localhost/sautiris"
        create_ris_app(settings=_make_settings(database_url=url))
        mock_engine.assert_called_once()
        assert mock_engine.call_args[0][0] == url


# ---------------------------------------------------------------------------
# GAP: get_db rollback failure path
# ---------------------------------------------------------------------------


class TestGetDbRollbackFailure:
    """When rollback fails during exception handling, the original error still propagates."""

    async def test_rollback_failure_does_not_hide_original_error(self) -> None:
        """Original exception propagates even when session.rollback() itself raises.

        Verifies that the double-try/except in get_db correctly logs the rollback
        failure and re-raises the original route-handler exception.
        """
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, MagicMock, patch

        import pytest

        from sautiris.api.deps import get_db

        original_error = RuntimeError("route handler blew up")

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock(side_effect=RuntimeError("rollback failed too"))

        @asynccontextmanager
        async def mock_factory():
            yield mock_session

        mock_request = MagicMock()
        mock_request.app.state.session_factory = mock_factory

        gen = get_db(mock_request)
        _ = await gen.__anext__()  # advance generator to yield; obtain the session

        with patch("sautiris.api.deps.logger") as mock_logger:
            with pytest.raises(RuntimeError, match="route handler blew up"):
                # Simulate the route handler raising an exception
                await gen.athrow(original_error)

            # Rollback failure must be logged — and must NOT replace original error
            mock_logger.error.assert_called()
            logged_event = mock_logger.error.call_args[0][0]
            assert "rollback_failed" in logged_event
