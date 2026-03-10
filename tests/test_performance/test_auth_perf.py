"""Performance tests for authentication subsystem.

Measures latency and throughput of API key verification and JWKS cache behaviour.
Run with: python -m pytest tests/test_performance/ -x -q -m performance
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.repositories.apikey_repo import ApiKeyRepository, generate_api_key, hash_key
from tests.conftest import TEST_TENANT_ID, TEST_USER_ID

# ---------------------------------------------------------------------------
# API Key Auth Performance
# ---------------------------------------------------------------------------


@pytest.mark.performance
class TestApiKeyAuthPerformance:
    """Performance tests for API key verification path."""

    async def test_api_key_verification_latency(self, db_session: AsyncSession) -> None:
        """Single key verification must complete in < 50ms (in-memory SQLite, no network)."""
        repo = ApiKeyRepository(db_session, TEST_TENANT_ID)
        raw_key, _api_key = await repo.create(
            name="perf-test-key",
            user_id=TEST_USER_ID,
            permissions=["order:read"],
            scopes=["read"],
        )

        start = time.perf_counter()
        result = await repo.verify(raw_key)
        elapsed = time.perf_counter() - start

        assert result is not None, "Key verification returned None"
        assert elapsed < 0.050, (
            f"Key verification took {elapsed * 1000:.2f}ms — expected < 50ms. "
            "This measures in-process SQLite round-trip with SHA-256 hash compare."
        )

    async def test_api_key_hash_computation_speed(self) -> None:
        """SHA-256 key hashing must be fast (< 1ms per hash) — it runs on every auth."""
        raw_key, _, _ = generate_api_key()

        iterations = 1000
        start = time.perf_counter()
        for _ in range(iterations):
            hash_key(raw_key)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 1.0, (
            f"SHA-256 hash averaged {avg_ms:.4f}ms — expected < 1ms per hash. "
            "If this fails, the hashing library or CPU may be severely throttled."
        )

    async def test_api_key_verification_with_prefix_collisions(
        self, db_session: AsyncSession
    ) -> None:
        """Verify the correct key is found even when multiple keys share the same prefix bucket.

        Uses 5 keys since the prefix is the first 12 chars (sautiris_XXX).
        Verification must complete in < 100ms even with collision scanning.
        """
        repo = ApiKeyRepository(db_session, TEST_TENANT_ID)

        # Create 5 keys — they will have the same "sautiris_" prefix category
        # but differ in the indexed prefix chars (probabilistically unique)
        created_keys: list[str] = []
        for i in range(5):
            raw_key, _ = await repo.create(
                name=f"perf-collision-key-{i}",
                user_id=TEST_USER_ID,
                permissions=["order:read"],
                scopes=["read"],
            )
            created_keys.append(raw_key)

        # Verify the last key (forces full candidate scan for its prefix bucket)
        target = created_keys[-1]
        start = time.perf_counter()
        result = await repo.verify(target)
        elapsed = time.perf_counter() - start

        assert result is not None, "Target key not found"
        assert elapsed < 0.100, (
            f"Prefix-collision verification took {elapsed * 1000:.2f}ms — expected < 100ms."
        )

    async def test_50_sequential_api_key_verifications(self, db_session: AsyncSession) -> None:
        """50 sequential verifications must complete in < 5s total.

        Measures sustained throughput of the auth path (10 req/s minimum).
        """
        repo = ApiKeyRepository(db_session, TEST_TENANT_ID)
        raw_key, _ = await repo.create(
            name="perf-sequential-key",
            user_id=TEST_USER_ID,
            permissions=["order:read"],
            scopes=["read"],
        )

        n = 50
        start = time.perf_counter()
        for _ in range(n):
            result = await repo.verify(raw_key)
            assert result is not None
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, (
            f"{n} sequential verifications took {elapsed:.2f}s — expected < 5s total."
        )

    async def test_expired_key_rejection_latency(self, db_session: AsyncSession) -> None:
        """Expired key rejection must be as fast as valid key verification (< 50ms)."""
        from sautiris.models.apikey import ApiKey

        raw_key, key_hash, key_prefix = generate_api_key()
        expired_key = ApiKey(
            id=uuid.uuid4(),
            tenant_id=TEST_TENANT_ID,
            name="expired-key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            user_id=TEST_USER_ID,
            permissions=["order:read"],
            scopes=["read"],
            is_active=True,
            expires_at=datetime.now(UTC) - timedelta(hours=1),  # already expired
        )
        db_session.add(expired_key)
        await db_session.flush()

        repo = ApiKeyRepository(db_session, TEST_TENANT_ID)
        start = time.perf_counter()
        result = await repo.verify(raw_key)
        elapsed = time.perf_counter() - start

        assert result is None, "Expired key should be rejected"
        assert elapsed < 0.050, (
            f"Expired key rejection took {elapsed * 1000:.2f}ms — expected < 50ms."
        )


# ---------------------------------------------------------------------------
# JWKS Cache Performance
# ---------------------------------------------------------------------------


@pytest.mark.performance
class TestJWKSCachePerformance:
    """Performance tests for Keycloak JWKS cache hit/miss scenarios."""

    def _make_provider_with_cache(self) -> object:
        """Create a KeycloakAuthProvider with pre-populated JWKS cache."""
        from sautiris.core.auth.keycloak import KeycloakAuthProvider

        provider = KeycloakAuthProvider(
            server_url="https://keycloak.example.com",
            realm="sautiris",
            client_id="sautiris-api",
            jwks_cache_ttl=600,
        )
        # Pre-populate the cache to simulate a warm-cache hit
        provider._jwks_cache = {"keys": [{"kid": "test-key", "kty": "RSA"}]}
        provider._cache_time = time.monotonic()  # just refreshed
        provider._effective_ttl = 600.0
        return provider

    async def test_jwks_cache_hit_latency(self) -> None:
        """JWKS cache hit (no network call) must resolve in < 1ms.

        A cache hit is purely an in-memory dict lookup and time comparison.
        """
        provider = self._make_provider_with_cache()

        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            result = await provider._get_jwks()  # type: ignore[attr-defined]
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 1.0, (
            f"JWKS cache hit averaged {avg_ms:.4f}ms — expected < 1ms. "
            "Cache hit should be a pure dict lookup with no I/O."
        )
        assert result == {"keys": [{"kid": "test-key", "kty": "RSA"}]}

    async def test_jwks_concurrent_cache_miss_single_http_call(self) -> None:
        """50 concurrent cache-miss requests should result in exactly ONE HTTP fetch.

        The asyncio.Lock in KeycloakAuthProvider prevents thundering herd:
        only one coroutine fetches from Keycloak; others wait and reuse the result.
        """
        from sautiris.core.auth.keycloak import KeycloakAuthProvider

        provider = KeycloakAuthProvider(
            server_url="https://keycloak.example.com",
            realm="sautiris",
            client_id="sautiris-api",
            jwks_cache_ttl=600,
        )
        # Cache is empty — all concurrent requests will see cache miss

        fetch_count = 0

        async def mock_get(url: str) -> MagicMock:
            nonlocal fetch_count
            fetch_count += 1
            # Simulate a tiny network delay
            await asyncio.sleep(0.01)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"keys": []}
            return mock_resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        provider._jwks_client = mock_client

        start = time.perf_counter()
        results = await asyncio.gather(*[provider._get_jwks() for _ in range(50)])
        elapsed = time.perf_counter() - start

        # All 50 coroutines must have received valid JWKS
        assert all(r == {"keys": []} for r in results), "Not all coroutines got valid JWKS"

        # Only ONE real HTTP call should have been made (thundering herd prevention)
        assert fetch_count == 1, (
            f"Expected 1 HTTP fetch under concurrent cache miss, got {fetch_count}. "
            "The asyncio.Lock double-check mechanism should prevent duplicate fetches."
        )

        # Total time should be close to just one fetch (10ms), not 50x fetches (500ms)
        assert elapsed < 0.5, (
            f"Concurrent JWKS cache miss took {elapsed:.3f}s — expected < 0.5s "
            "(one real fetch + lock overhead for 50 waiters)."
        )

    async def test_jwks_cache_prevents_repeated_fetches_under_ttl(self) -> None:
        """After one successful fetch, subsequent calls within TTL must NOT re-fetch."""
        from sautiris.core.auth.keycloak import KeycloakAuthProvider

        provider = KeycloakAuthProvider(
            server_url="https://keycloak.example.com",
            realm="sautiris",
            client_id="sautiris-api",
            jwks_cache_ttl=600,
        )

        call_count = 0

        async def mock_get(url: str) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"keys": [{"kid": "k1"}]}
            return mock_resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        provider._jwks_client = mock_client

        # First call — populates cache
        await provider._get_jwks()
        assert call_count == 1

        # 20 subsequent calls — all should be cache hits
        for _ in range(20):
            await provider._get_jwks()

        assert call_count == 1, (
            f"Expected 1 total HTTP call, got {call_count}. "
            "JWKS must be served from cache within TTL."
        )
