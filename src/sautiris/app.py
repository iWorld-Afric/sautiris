"""FastAPI application factory for SautiRIS."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sautiris.api.middleware.audit_middleware import AuditMiddleware
from sautiris.api.middleware.error_handler import unhandled_exception_handler
from sautiris.api.middleware.rate_limit import RateLimitMiddleware
from sautiris.api.router import api_router
from sautiris.config import SautiRISSettings
from sautiris.core.auth.base import AuthProvider
from sautiris.core.auth.keycloak import KeycloakAuthProvider
from sautiris.core.auth.oauth2 import OAuth2AuthProvider
from sautiris.core.events import EventBus


def create_ris_app(
    settings: SautiRISSettings | None = None,
    *,
    api_prefix: str | None = None,
    **overrides: Any,
) -> FastAPI:
    """Create and configure the SautiRIS FastAPI application.

    Can be used standalone or mounted into another FastAPI app.

    Args:
        settings: Pre-built settings object.  Falls back to env + *overrides*.
        api_prefix: Override the internal API prefix.  Pass ``""`` when mounting
            as a sub-application so routes don't double-prefix.  Defaults to
            ``"/api/v1"`` for standalone usage.
        **overrides: Keyword arguments forwarded to ``SautiRISSettings``.

    Raises:
        ConfigurationError: If security settings are invalid (CORS wildcard +
            credentials, missing encryption key in production, etc.).
    """
    if settings is None:
        settings = SautiRISSettings(**overrides)

    # --- Startup validation (issue #4, #6) ---
    settings.validate_security()

    # --- Database ---
    engine = create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # --- Auth provider ---
    auth: AuthProvider
    if settings.auth_provider == "keycloak":
        auth = KeycloakAuthProvider(
            server_url=settings.keycloak_server_url,
            realm=settings.keycloak_realm,
            client_id=settings.keycloak_client_id,
            jwks_url=settings.keycloak_jwks_url,
            jwks_cache_ttl=settings.jwks_cache_ttl,
            jwks_key_miss_refetch_interval=settings.jwks_key_miss_refetch_interval,
        )
    elif settings.auth_provider == "oauth2":
        auth = OAuth2AuthProvider(
            jwks_url=settings.oauth2_jwks_url,
            issuer=settings.oauth2_issuer,
            audience=settings.oauth2_audience,
            jwks_cache_ttl=settings.jwks_cache_ttl,
            jwks_key_miss_refetch_interval=settings.jwks_key_miss_refetch_interval,
        )
    else:
        from sautiris.core.auth.apikey import APIKeyAuthProvider  # noqa: PLC0415

        auth = APIKeyAuthProvider(
            header_name=settings.api_key_header,
            session_factory=session_factory,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        yield
        await engine.dispose()
        if hasattr(app.state, "auth_provider") and hasattr(app.state.auth_provider, "close"):
            await app.state.auth_provider.close()

    app = FastAPI(
        title="SautiRIS",
        description="Open-source Radiology Information System",
        version="1.0.0a2",
        lifespan=lifespan,
    )

    # --- Store per-app state (no module-level globals) ---
    app.state.session_factory = session_factory
    app.state.auth_provider = auth
    app.state.event_bus = EventBus()
    app.state.settings = settings

    # --- Exception handlers (issue #45) ---
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # --- CORS middleware (issue #4) ---
    # cors_origins defaults to [] — operators must configure explicitly.
    # Wildcard + credentials is rejected by validate_security() above.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # --- Rate limiting middleware (issue #40) ---
    app.add_middleware(RateLimitMiddleware, settings=settings)

    # --- Audit middleware (issue #22) — must run after rate limiting ---
    app.add_middleware(AuditMiddleware)

    # --- Routers ---
    _prefix = "/api/v1" if api_prefix is None else api_prefix
    app.include_router(api_router, prefix=_prefix)

    return app
