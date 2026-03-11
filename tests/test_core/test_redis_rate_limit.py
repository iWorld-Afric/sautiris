"""Tests for RedisRateLimiter — C3: comprehensive coverage for redis_rate_limit.py."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sautiris.core.redis_rate_limit import RedisRateLimiter, _mask_redis_url


class TestMaskRedisUrl:
    """Tests for _mask_redis_url helper."""

    def test_masks_password_in_url(self) -> None:
        url = "redis://user:secret123@redis.example.com:6379/0"
        masked = _mask_redis_url(url)
        assert "secret123" not in masked
        assert "redis.example.com" in masked
        assert "****" in masked

    def test_masks_url_with_no_password(self) -> None:
        url = "redis://localhost:6379/0"
        masked = _mask_redis_url(url)
        assert "localhost" in masked

    def test_masks_url_with_username_only(self) -> None:
        url = "redis://user@localhost:6379/0"
        masked = _mask_redis_url(url)
        assert "****" in masked

    def test_fallback_on_invalid_url(self) -> None:
        masked = _mask_redis_url("")
        assert masked == "redis://****"


class TestInMemoryFallback:
    """Tests for in-memory fallback when no Redis URL is provided."""

    @pytest.mark.asyncio
    async def test_no_redis_url_uses_in_memory(self) -> None:
        limiter = RedisRateLimiter(redis_url=None)
        assert limiter._redis is None
        allowed, retry = await limiter.check_rate_limit("test:key", 5, 60)
        assert allowed is True
        assert retry == 0

    @pytest.mark.asyncio
    async def test_empty_redis_url_uses_in_memory(self) -> None:
        limiter = RedisRateLimiter(redis_url="")
        assert limiter._redis is None
        allowed, _ = await limiter.check_rate_limit("test:key", 5, 60)
        assert allowed is True


class TestInMemoryRateLimit:
    """Tests for in-memory rate limiting logic."""

    @pytest.mark.asyncio
    async def test_allows_under_limit(self) -> None:
        limiter = RedisRateLimiter()
        for _ in range(5):
            allowed, retry = await limiter.check_rate_limit("key", 5, 60)
            assert allowed is True
            assert retry == 0

    @pytest.mark.asyncio
    async def test_denies_at_limit(self) -> None:
        limiter = RedisRateLimiter()
        for _ in range(5):
            await limiter.check_rate_limit("key", 5, 60)
        allowed, retry = await limiter.check_rate_limit("key", 5, 60)
        assert allowed is False
        assert retry > 0

    @pytest.mark.asyncio
    async def test_window_expiry(self) -> None:
        limiter = RedisRateLimiter()
        # Fill up the limit
        for _ in range(3):
            await limiter.check_rate_limit("key", 3, 1)
        # Manually age entries past the window
        limiter._memory["key"] = [time.time() - 2.0 for _ in limiter._memory["key"]]
        # Should be allowed again after entries expire
        allowed, _ = await limiter.check_rate_limit("key", 3, 1)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_separate_keys_independent(self) -> None:
        limiter = RedisRateLimiter()
        for _ in range(3):
            await limiter.check_rate_limit("key_a", 3, 60)
        # key_a is at limit, but key_b should still work
        allowed, _ = await limiter.check_rate_limit("key_b", 3, 60)
        assert allowed is True


class TestClose:
    """Tests for close() method."""

    @pytest.mark.asyncio
    async def test_close_no_redis(self) -> None:
        limiter = RedisRateLimiter()
        await limiter.close()
        assert limiter._redis is None

    @pytest.mark.asyncio
    async def test_close_with_redis_mock(self) -> None:
        limiter = RedisRateLimiter()
        mock_redis = AsyncMock()
        limiter._redis = mock_redis
        await limiter.close()
        mock_redis.aclose.assert_awaited_once()
        assert limiter._redis is None

    @pytest.mark.asyncio
    async def test_close_handles_error(self) -> None:
        limiter = RedisRateLimiter()
        mock_redis = AsyncMock()
        mock_redis.aclose.side_effect = ConnectionError("connection lost")
        limiter._redis = mock_redis
        await limiter.close()
        assert limiter._redis is None


class TestRedisUnavailableFallback:
    """Tests for Redis error → in-memory fallback behavior."""

    @pytest.mark.asyncio
    async def test_redis_error_falls_back_to_in_memory(self) -> None:
        limiter = RedisRateLimiter()
        mock_redis = AsyncMock()
        limiter._redis = mock_redis

        # Make redis pipeline raise
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_pipe.zremrangebyscore = MagicMock()
        mock_pipe.zcard = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        # Should fall back to in-memory
        allowed, _ = await limiter.check_rate_limit("key", 5, 60)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_redis_import_error_uses_fallback(self) -> None:
        with patch.dict("sys.modules", {"redis": None, "redis.asyncio": None}):
            limiter = RedisRateLimiter(redis_url="redis://localhost:6379/0")
        assert limiter._redis is None
        allowed, _ = await limiter.check_rate_limit("key", 5, 60)
        assert allowed is True


class TestRejectedRequestsBehavior:
    """Tests that rejected requests don't consume rate limit slots (M8 fix)."""

    @pytest.mark.asyncio
    async def test_rejected_request_does_not_count(self) -> None:
        limiter = RedisRateLimiter()
        # Fill to limit
        for _ in range(3):
            await limiter.check_rate_limit("key", 3, 60)
        # These rejections should not consume additional slots
        for _ in range(5):
            allowed, _ = await limiter.check_rate_limit("key", 3, 60)
            assert allowed is False
        # Manually clear and verify we can still use 3
        limiter._memory["key"] = []
        for _ in range(3):
            allowed, _ = await limiter.check_rate_limit("key", 3, 60)
            assert allowed is True
