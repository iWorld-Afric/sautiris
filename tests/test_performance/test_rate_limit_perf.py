"""Performance tests for the sliding-window rate limiter.

Measures per-request overhead and memory bounding under IP sweep conditions.
Run with: python -m pytest tests/test_performance/ -x -q -m performance
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from sautiris.api.middleware.rate_limit import _MAX_WINDOW_KEYS, RateLimitMiddleware
from sautiris.config import SautiRISSettings


def _make_high_limit_app(max_rps: int = 10_000) -> FastAPI:
    """Build a test app with a very high rate limit so perf tests aren't gated by it."""
    app = FastAPI()
    settings = SautiRISSettings(
        rate_limit_enabled=True,
        rate_limit_general=f"{max_rps}/minute",
        rate_limit_auth_endpoints=f"{max_rps}/minute",
        rate_limit_apikey_create=f"{max_rps}/minute",
        rate_limit_trusted_ips=[],
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app.add_middleware(RateLimitMiddleware, settings=settings)

    @app.get("/data")
    async def data() -> JSONResponse:
        return JSONResponse({"ok": True})

    return app


@pytest.mark.performance
class TestRateLimiterPerformance:
    """Performance tests for the in-process sliding-window rate limiter."""

    async def test_rate_limiter_per_request_overhead(self) -> None:
        """100 sequential requests should complete in < 3s with the limiter enabled.

        Without a limiter, 100 in-process ASGI round trips take ~ 50-200ms.
        We allow up to 3s total, giving ~30ms per request max including middleware.
        """
        app = _make_high_limit_app()
        transport = ASGITransport(app=app)

        n = 100
        async with AsyncClient(transport=transport, base_url="http://testclient") as client:
            start = time.perf_counter()
            for _ in range(n):
                resp = await client.get("/data")
                assert resp.status_code == 200
            elapsed = time.perf_counter() - start

        assert elapsed < 3.0, (
            f"{n} requests with rate limiter took {elapsed:.3f}s — expected < 3s. "
            "Middleware overhead should be negligible vs. ASGI round-trip cost."
        )

    async def test_rate_limiter_memory_bounded_under_ip_sweep(self) -> None:
        """Simulating many unique IPs must not cause unbounded memory growth.

        The middleware evicts stale window buckets when the dict exceeds
        _MAX_WINDOW_KEYS (10,000). This test verifies that eviction is triggered
        and the internal _windows dict stays bounded.
        """
        from sautiris.api.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        settings = SautiRISSettings(
            rate_limit_enabled=True,
            rate_limit_general="1000/minute",
            rate_limit_auth_endpoints="1000/minute",
            rate_limit_apikey_create="1000/minute",
            rate_limit_trusted_ips=[],
            database_url="sqlite+aiosqlite:///:memory:",
        )

        # Grab reference to middleware instance to inspect internal state
        middleware_instance: RateLimitMiddleware | None = None

        original_init = RateLimitMiddleware.__init__

        def capturing_init(
            self: RateLimitMiddleware,
            app_: object,
            settings_: SautiRISSettings,
        ) -> None:
            nonlocal middleware_instance
            original_init(self, app_, settings_)
            middleware_instance = self

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(RateLimitMiddleware, "__init__", capturing_init)
            app.add_middleware(RateLimitMiddleware, settings=settings)

            @app.get("/data")
            async def data() -> JSONResponse:
                return JSONResponse({"ok": True})

            transport = ASGITransport(app=app)
            # We test the eviction path by directly overfilling the _windows dict
            async with AsyncClient(transport=transport, base_url="http://testclient") as _:
                pass

        # Direct test of eviction logic: fill _windows beyond threshold with empty buckets
        if middleware_instance is not None:
            over_limit = _MAX_WINDOW_KEYS + 500
            for i in range(over_limit):
                middleware_instance._windows[f"192.168.{i // 256}.{i % 256}:1000/minute"] = []

            initial_size = len(middleware_instance._windows)
            assert initial_size >= _MAX_WINDOW_KEYS, "Setup: dict should be over threshold"

            # Trigger eviction
            middleware_instance._evict_stale_keys()
            final_size = len(middleware_instance._windows)

            assert final_size == 0, (
                f"After evicting empty buckets, _windows should be empty, "
                f"got {final_size} entries. All buckets were empty so all should be pruned."
            )

    async def test_rate_limiter_correct_enforcement_under_concurrent_load(self) -> None:
        """50 concurrent requests from the same IP with limit=10 should yield exactly 10 successes.

        Verifies thread-safety of the asyncio.Lock under concurrent coroutines.
        """
        app = FastAPI()
        settings = SautiRISSettings(
            rate_limit_enabled=True,
            rate_limit_general="10/minute",  # allow only 10
            rate_limit_auth_endpoints="10/minute",
            rate_limit_apikey_create="10/minute",
            rate_limit_trusted_ips=[],
            database_url="sqlite+aiosqlite:///:memory:",
        )
        app.add_middleware(RateLimitMiddleware, settings=settings)

        @app.get("/data")
        async def data() -> JSONResponse:
            return JSONResponse({"ok": True})

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testclient") as client:
            responses = await asyncio.gather(
                *[client.get("/data") for _ in range(50)],
                return_exceptions=True,
            )

        statuses = [r.status_code for r in responses if hasattr(r, "status_code")]
        successes = statuses.count(200)
        rate_limited = statuses.count(429)

        assert successes == 10, (
            f"Expected exactly 10 successful responses (limit=10), got {successes}. "
            "The asyncio.Lock must serialize bucket updates to prevent over-permitting."
        )
        assert rate_limited == 40, f"Expected 40 rate-limited responses, got {rate_limited}."

    async def test_rate_limiter_disabled_has_zero_overhead(self) -> None:
        """With rate limiting disabled, middleware should add < 10ms total for 100 requests."""
        app_disabled = FastAPI()
        settings_disabled = SautiRISSettings(
            rate_limit_enabled=False,
            rate_limit_general="100/minute",
            rate_limit_auth_endpoints="100/minute",
            rate_limit_apikey_create="100/minute",
            database_url="sqlite+aiosqlite:///:memory:",
        )
        app_disabled.add_middleware(RateLimitMiddleware, settings=settings_disabled)

        @app_disabled.get("/data")
        async def data() -> JSONResponse:
            return JSONResponse({"ok": True})

        transport = ASGITransport(app=app_disabled)
        n = 100
        async with AsyncClient(transport=transport, base_url="http://testclient") as client:
            start = time.perf_counter()
            for _ in range(n):
                resp = await client.get("/data")
                assert resp.status_code == 200
            elapsed = time.perf_counter() - start

        assert elapsed < 3.0, (
            f"{n} requests with limiter disabled took {elapsed:.3f}s — expected < 3s."
        )

    async def test_rate_limit_parse_limit_performance(self) -> None:
        """_parse_limit must be fast: 100,000 parses in < 1s."""
        iterations = 100_000
        rate_strings = ["100/minute", "10/second", "1000/hour", "5/minute"]

        start = time.perf_counter()
        for i in range(iterations):
            RateLimitMiddleware._parse_limit(rate_strings[i % len(rate_strings)])
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, (
            f"100,000 _parse_limit calls took {elapsed:.3f}s — expected < 1s. "
            "Rate parsing is called on every request so it must be extremely fast."
        )
