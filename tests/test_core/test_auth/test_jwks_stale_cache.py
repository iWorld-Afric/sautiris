"""Tests for SEC-2: stale JWKS cache fallback in both auth providers.

When JWKS fetch fails (httpx.HTTPError), providers should return stale cache
if available, and only raise 503 when no cache exists (cold start).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from sautiris.core.auth.keycloak import KeycloakAuthProvider
from sautiris.core.auth.oauth2 import OAuth2AuthProvider


def _make_keycloak(ttl: int = 600) -> KeycloakAuthProvider:
    return KeycloakAuthProvider(
        server_url="https://auth.example.com",
        realm="test",
        client_id="ris-app",
        jwks_url="https://auth.example.com/realms/test/certs",
        jwks_cache_ttl=ttl,
    )


def _make_oauth2(ttl: int = 600) -> OAuth2AuthProvider:
    return OAuth2AuthProvider(
        jwks_url="https://idp.example.com/.well-known/jwks.json",
        issuer="https://idp.example.com",
        audience="my-ris",
        jwks_cache_ttl=ttl,
    )


def _prime_cache(provider: KeycloakAuthProvider | OAuth2AuthProvider) -> dict[str, object]:
    """Pre-populate the cache with stale data (expired TTL)."""
    stale_jwks = {"keys": [{"kid": "stale-key", "kty": "RSA"}]}
    provider._jwks_cache = stale_jwks
    # Set cache_time far in the past so TTL has expired
    provider._cache_time = time.monotonic() - 99999
    return stale_jwks


class TestKeycloakStaleCacheFallback:
    """Keycloak: JWKS fetch failure returns stale cache if available."""

    async def test_stale_cache_returned_on_fetch_failure(self) -> None:
        """HTTP error + stale cache → return stale cache (not 503)."""
        provider = _make_keycloak(ttl=1)
        stale = _prime_cache(provider)

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        provider._jwks_client = mock_client

        result = await provider._get_jwks()
        assert result == stale

    async def test_503_when_no_cache_exists(self) -> None:
        """HTTP error + no cache at all → 503."""
        provider = _make_keycloak()
        provider._jwks_cache = None

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        provider._jwks_client = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await provider._get_jwks()
        assert exc_info.value.status_code == 503


class TestOAuth2StaleCacheFallback:
    """OAuth2: JWKS fetch failure returns stale cache if available."""

    async def test_stale_cache_returned_on_fetch_failure(self) -> None:
        """HTTP error + stale cache → return stale cache (not 503)."""
        provider = _make_oauth2(ttl=1)
        stale = _prime_cache(provider)

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout", request=None)
        provider._jwks_client = mock_client

        result = await provider._get_jwks()
        assert result == stale

    async def test_503_when_no_cache_exists(self) -> None:
        """HTTP error + no cache at all → 503."""
        provider = _make_oauth2()
        provider._jwks_cache = None

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout", request=None)
        provider._jwks_client = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await provider._get_jwks()
        assert exc_info.value.status_code == 503
