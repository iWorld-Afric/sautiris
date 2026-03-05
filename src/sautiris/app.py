"""FastAPI application factory for SautiRIS."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sautiris.api.deps import set_auth_provider, set_session_factory
from sautiris.api.router import api_router
from sautiris.config import SautiRISSettings
from sautiris.core.auth.base import AuthProvider
from sautiris.core.auth.keycloak import KeycloakAuthProvider
from sautiris.core.auth.oauth2 import OAuth2AuthProvider
from sautiris.core.tenancy import TenantMiddleware


def create_ris_app(
    settings: SautiRISSettings | None = None,
    **overrides: Any,
) -> FastAPI:
    """Create and configure the SautiRIS FastAPI application.

    Can be used standalone or mounted into another FastAPI app.
    """
    if settings is None:
        settings = SautiRISSettings(**overrides)

    app = FastAPI(
        title="SautiRIS",
        description="Open-source Radiology Information System",
        version="1.0.0a1",
    )

    # Database engine
    engine = create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(session_factory)

    # Auth provider
    auth: AuthProvider
    if settings.auth_provider == "keycloak":
        auth = KeycloakAuthProvider(
            server_url=settings.keycloak_server_url,
            realm=settings.keycloak_realm,
            client_id=settings.keycloak_client_id,
            jwks_url=settings.keycloak_jwks_url,
        )
    elif settings.auth_provider == "oauth2":
        auth = OAuth2AuthProvider(
            jwks_url=settings.oauth2_jwks_url,
            issuer=settings.oauth2_issuer,
            audience=settings.oauth2_audience,
        )
    else:
        from sautiris.core.auth.apikey import APIKeyAuthProvider

        auth = APIKeyAuthProvider(
            header_name=settings.api_key_header,
            session_factory=session_factory,
        )
    set_auth_provider(auth)

    # Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        TenantMiddleware,
        header_name=settings.tenant_header,
        jwt_claim=settings.tenant_jwt_claim,
    )

    # Routers
    app.include_router(api_router)

    return app
