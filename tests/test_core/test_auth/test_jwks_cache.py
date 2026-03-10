"""Tests for JWKS TTL cache with jitter and key-miss refetch (issue #2)."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from sautiris.core.auth.keycloak import KeycloakAuthProvider
from sautiris.core.auth.oauth2 import OAuth2AuthProvider


class TestKeycloakJwksCache:
    """Keycloak provider JWKS TTL cache behaviour."""

    def _make_provider(self, ttl: int = 10, miss_interval: int = 5) -> KeycloakAuthProvider:
        return KeycloakAuthProvider(
            server_url="https://auth.example.com",
            realm="test",
            client_id="app",
            jwks_url="https://auth.example.com/realms/test/certs",
            jwks_cache_ttl=ttl,
            jwks_key_miss_refetch_interval=miss_interval,
        )

    async def test_first_call_fetches_jwks(self) -> None:
        provider = self._make_provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        provider._jwks_client = mock_client

        result = await provider._get_jwks()
        assert result == {"keys": [{"kid": "key1"}]}
        mock_client.get.assert_called_once()

    async def test_cache_hit_skips_fetch(self) -> None:
        provider = self._make_provider(ttl=600)
        jwks = {"keys": [{"kid": "key1"}]}
        provider._jwks_cache = jwks
        provider._cache_time = time.monotonic()  # just fetched

        mock_client = AsyncMock()
        provider._jwks_client = mock_client

        result = await provider._get_jwks()
        assert result == jwks
        mock_client.get.assert_not_called()

    async def test_stale_cache_triggers_refetch(self) -> None:
        provider = self._make_provider(ttl=1)  # 1 second TTL
        old_jwks = {"keys": [{"kid": "old"}]}
        new_jwks = {"keys": [{"kid": "new"}]}
        provider._jwks_cache = old_jwks
        provider._cache_time = time.monotonic() - 10  # 10s ago — stale

        mock_response = MagicMock()
        mock_response.json.return_value = new_jwks
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        provider._jwks_client = mock_client

        result = await provider._get_jwks()
        assert result == new_jwks
        mock_client.get.assert_called_once()

    async def test_force_refetch_updates_cache(self) -> None:
        provider = self._make_provider(ttl=600, miss_interval=5)
        old_jwks = {"keys": [{"kid": "old"}]}
        new_jwks = {"keys": [{"kid": "rotated"}]}
        provider._jwks_cache = old_jwks
        provider._cache_time = time.monotonic()
        # last forced refetch was long enough ago
        provider._last_key_miss_refetch = time.monotonic() - 60

        mock_response = MagicMock()
        mock_response.json.return_value = new_jwks
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        provider._jwks_client = mock_client

        result = await provider._get_jwks(force=True)
        assert result == new_jwks
        mock_client.get.assert_called_once()

    async def test_forced_refetch_rate_limited(self) -> None:
        """Two forced refetches in quick succession: second must be throttled."""
        provider = self._make_provider(ttl=600, miss_interval=60)
        cached_jwks = {"keys": [{"kid": "key1"}]}
        provider._jwks_cache = cached_jwks
        provider._cache_time = time.monotonic()
        provider._last_key_miss_refetch = time.monotonic()  # just done

        mock_client = AsyncMock()
        provider._jwks_client = mock_client

        result = await provider._get_jwks(force=True)
        assert result == cached_jwks  # returns cached, no HTTP call
        mock_client.get.assert_not_called()


class TestOAuth2JwksCache:
    """OAuth2 provider JWKS TTL cache mirrors Keycloak behaviour."""

    def _make_provider(self, ttl: int = 10) -> OAuth2AuthProvider:
        return OAuth2AuthProvider(
            jwks_url="https://idp.example.com/.well-known/jwks.json",
            issuer="https://idp.example.com",
            audience="my-api",
            jwks_cache_ttl=ttl,
            jwks_key_miss_refetch_interval=5,
        )

    async def test_cache_hit_skips_fetch(self) -> None:
        provider = self._make_provider(ttl=600)
        jwks = {"keys": [{"kid": "k1"}]}
        provider._jwks_cache = jwks
        provider._cache_time = time.monotonic()

        mock_client = AsyncMock()
        provider._jwks_client = mock_client

        result = await provider._get_jwks()
        assert result == jwks
        mock_client.get.assert_not_called()

    async def test_stale_triggers_refetch(self) -> None:
        provider = self._make_provider(ttl=1)
        provider._jwks_cache = {"keys": [{"kid": "old"}]}
        provider._cache_time = time.monotonic() - 10

        new_jwks: dict[str, Any] = {"keys": [{"kid": "new"}]}
        mock_response = MagicMock()
        mock_response.json.return_value = new_jwks
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        provider._jwks_client = mock_client

        result = await provider._get_jwks()
        assert result == new_jwks


# ---------------------------------------------------------------------------
# M15: JWKS close() method tests
# ---------------------------------------------------------------------------


class TestJWKSClose:
    """M15: verify close() properly closes the HTTP client."""

    async def test_close_with_client(self) -> None:
        provider = KeycloakAuthProvider(
            server_url="https://auth.example.com",
            realm="test",
            client_id="app",
        )
        mock_client = AsyncMock()
        provider._jwks_client = mock_client
        await provider.close()
        mock_client.aclose.assert_awaited_once()

    async def test_close_without_client(self) -> None:
        provider = OAuth2AuthProvider(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="app",
        )
        assert provider._jwks_client is None
        await provider.close()  # should not raise
