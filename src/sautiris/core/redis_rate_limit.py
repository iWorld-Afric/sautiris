"""Redis-backed sliding window rate limiter with in-memory fallback.

This module provides a :class:`RedisRateLimiter` that uses Redis sorted sets
to implement a sliding-window counter.  When ``redis_url`` is not supplied or
the ``redis`` package is unavailable the limiter transparently falls back to a
simple in-memory implementation that is suitable for single-process deployments.

Usage::

    limiter = RedisRateLimiter(redis_url="redis://localhost:6379/0")
    allowed, retry_after = await limiter.check_rate_limit(
        key="tenant:abc123:login",
        max_requests=10,
        window_seconds=60,
    )
    if not allowed:
        raise HTTPException(status_code=429, headers={"Retry-After": str(retry_after)})
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _mask_redis_url(url: str) -> str:
    """Mask credentials in a Redis URL for safe logging."""
    from urllib.parse import urlparse, urlunparse  # noqa: PLC0415

    if not url or "://" not in url:
        return "redis://****"
    try:
        parsed = urlparse(url)
        if parsed.password or parsed.username:
            masked_netloc = f"**:****@{parsed.hostname}"
            if parsed.port:
                masked_netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=masked_netloc))
        return url
    except Exception:
        return "redis://****"


class RedisRateLimiter:
    """Redis-backed sliding window rate limiter.

    Falls back to in-memory rate limiting when ``redis_url`` is ``None`` /
    empty, or when the ``redis`` package is not installed, or when a Redis
    operation fails.

    Thread-safety note: the in-memory fallback is *not* safe for multi-process
    deployments — use Redis in production.

    Args:
        redis_url: Full Redis connection URL, e.g.
            ``"redis://localhost:6379/0"`` or
            ``"rediss://user:pass@redis.example.com:6380/1"``.
            ``None`` or ``""`` disables Redis and uses in-memory fallback.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        # _redis is typed as Any because the redis.asyncio stubs are optional.
        self._redis: Any = None
        self._memory: dict[str, list[float]] = defaultdict(list)

        if redis_url:
            try:
                # redis is an optional dependency; import inside try/except so
                # mypy handles the missing-module case via the except branch.
                import redis.asyncio as aioredis  # noqa: PLC0415

                self._redis = aioredis.from_url(  # type: ignore[no-untyped-call]
                    redis_url, decode_responses=False
                )
                logger.info("redis_rate_limit.connected", url=_mask_redis_url(redis_url))
            except ImportError:
                logger.warning(
                    "redis_rate_limit.redis_not_installed",
                    msg=(
                        "The 'redis' package is not installed. "
                        "Falling back to in-memory rate limiting."
                    ),
                )

    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Check whether a request is within the configured rate limit.

        Args:
            key: Arbitrary string that identifies the rate-limited entity
                (e.g. ``"ip:1.2.3.4"`` or ``"tenant:abc:user:xyz"``).
            max_requests: Maximum number of requests allowed in *window_seconds*.
            window_seconds: Width of the sliding window in seconds.

        Returns:
            A ``(allowed, retry_after_seconds)`` tuple.
            *allowed* is ``True`` when the request is within the limit.
            *retry_after_seconds* is ``0`` when *allowed* is ``True``, or the
            number of seconds the caller should wait before retrying.
        """
        if self._redis is not None:
            try:
                return await self._redis_check(key, max_requests, window_seconds)
            except Exception:
                logger.warning(
                    "redis_rate_limit.redis_error_fallback",
                    key=key,
                    msg="Redis check failed; falling back to in-memory.",
                    exc_info=True,
                )
        return await self._in_memory_check(key, max_requests, window_seconds)

    async def close(self) -> None:
        """Close the underlying Redis connection pool (if any).

        Call this during application shutdown to release resources.
        """
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                logger.warning(
                    "redis_rate_limit.close_error",
                    msg="Error closing Redis connection.",
                    exc_info=True,
                )
            finally:
                self._redis = None

    # ------------------------------------------------------------------
    # Redis implementation — sorted set sliding window
    # ------------------------------------------------------------------

    async def _redis_check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Sliding-window counter using a Redis sorted set.

        Algorithm:
        1. Remove expired members outside the window.
        2. Count remaining members.
        3. If under limit, add the current request and set TTL.
        4. If over limit, compute retry-after.
        """
        redis_key = f"ratelimit:{key}"
        now = time.time()
        window_start = now - window_seconds

        # Phase 1: prune expired entries and count current usage
        pipe: Any = self._redis.pipeline()
        pipe.zremrangebyscore(redis_key, "-inf", window_start)
        pipe.zcard(redis_key)
        results: list[Any] = await pipe.execute()

        current_count = int(results[1])

        if current_count < max_requests:
            # Phase 2: under limit — add this request
            member = f"{now:.6f}:{secrets.token_hex(8)}"
            pipe2: Any = self._redis.pipeline()
            pipe2.zadd(redis_key, {member: now})
            pipe2.expire(redis_key, window_seconds * 2)
            await pipe2.execute()
            return True, 0

        # Over limit — compute retry-after from oldest entry
        oldest_entries: list[tuple[bytes, float]] = await self._redis.zrange(
            redis_key, 0, 0, withscores=True
        )
        if oldest_entries:
            oldest_score = oldest_entries[0][1]
            retry_after = max(1, int(oldest_score + window_seconds - now) + 1)
        else:
            retry_after = window_seconds

        return False, retry_after

    # ------------------------------------------------------------------
    # In-memory fallback — simple list-based sliding window
    # ------------------------------------------------------------------

    async def _in_memory_check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Simple in-memory sliding window counter.

        Not suitable for multi-process or distributed deployments.
        """
        now = time.time()
        window_start = now - window_seconds

        # Prune expired timestamps.
        self._memory[key] = [ts for ts in self._memory[key] if ts >= window_start]

        if len(self._memory[key]) >= max_requests:
            oldest = self._memory[key][0]
            retry_after = max(1, int(oldest + window_seconds - now) + 1)
            return False, retry_after

        self._memory[key].append(now)
        return True, 0
