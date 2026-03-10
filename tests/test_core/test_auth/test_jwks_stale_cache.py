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
    # Set cache_time in the past so TTL has expired, but within MAX_STALE_AGE (86400s)
    provider._cache_time = time.monotonic() - 3600  # 1 hour ago
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


class TestMaxStaleAgeBoundary:
    """#54: MAX_STALE_AGE boundary — cache older than 24 h raises 503; younger returns stale."""

    async def test_cache_just_within_max_stale_age_returns_stale(self) -> None:
        """Cache aged (MAX_STALE_AGE - 1) seconds is still within limit → return stale."""
        from sautiris.core.auth.jwks_base import MAX_STALE_AGE

        provider = _make_keycloak(ttl=1)
        stale_jwks = {"keys": [{"kid": "stale-key", "kty": "RSA"}]}
        provider._jwks_cache = stale_jwks
        # Cache time just within MAX_STALE_AGE (1 second under the limit)
        provider._cache_time = time.monotonic() - (MAX_STALE_AGE - 1)

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        provider._jwks_client = mock_client

        result = await provider._get_jwks()
        assert result == stale_jwks

    async def test_cache_at_exactly_max_stale_age_raises_503(self) -> None:
        """Cache aged exactly MAX_STALE_AGE seconds is expired → raise 503.

        The boundary check is ``cache_age < MAX_STALE_AGE`` (strict less-than),
        so age == MAX_STALE_AGE is over the limit.
        """
        from sautiris.core.auth.jwks_base import MAX_STALE_AGE

        provider = _make_keycloak(ttl=1)
        provider._jwks_cache = {"keys": [{"kid": "expired-key"}]}
        # Place cache_time exactly MAX_STALE_AGE seconds in the past
        provider._cache_time = time.monotonic() - MAX_STALE_AGE

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        provider._jwks_client = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await provider._get_jwks()
        assert exc_info.value.status_code == 503

    async def test_cache_beyond_max_stale_age_raises_503(self) -> None:
        """Cache aged (MAX_STALE_AGE + 1) seconds → raise 503 (definitely expired)."""
        from sautiris.core.auth.jwks_base import MAX_STALE_AGE

        provider = _make_oauth2(ttl=1)
        provider._jwks_cache = {"keys": [{"kid": "very-old-key"}]}
        provider._cache_time = time.monotonic() - (MAX_STALE_AGE + 1)

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout", request=None)
        provider._jwks_client = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await provider._get_jwks()
        assert exc_info.value.status_code == 503

    async def test_max_stale_age_is_24_hours(self) -> None:
        """MAX_STALE_AGE must be exactly 86 400 seconds (24 hours)."""
        from sautiris.core.auth.jwks_base import MAX_STALE_AGE

        assert MAX_STALE_AGE == 86_400


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
