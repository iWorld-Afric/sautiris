"""Tests for rate limiting middleware (issue #40)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from sautiris.api.middleware.rate_limit import RateLimitMiddleware
from sautiris.config import SautiRISSettings


def _make_limited_app(
    general_rate: str = "3/minute",
    enabled: bool = True,
) -> FastAPI:
    app = FastAPI()
    settings = SautiRISSettings(
        rate_limit_enabled=enabled,
        rate_limit_general=general_rate,
        rate_limit_auth_endpoints="2/minute",
        rate_limit_apikey_create="1/minute",
        rate_limit_trusted_ips=[],
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app.add_middleware(RateLimitMiddleware, settings=settings)

    @app.get("/data")
    async def data() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return app


class TestRateLimitMiddleware:
    async def test_requests_within_limit_succeed(self) -> None:
        app = _make_limited_app(general_rate="5/minute")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(5):
                resp = await client.get("/data")
                assert resp.status_code == 200

    async def test_exceeding_limit_returns_429(self) -> None:
        app = _make_limited_app(general_rate="3/minute")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(3):
                await client.get("/data")
            # 4th request should be rate-limited
            resp = await client.get("/data")
            assert resp.status_code == 429

    async def test_429_includes_retry_after_header(self) -> None:
        app = _make_limited_app(general_rate="2/minute")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/data")
            await client.get("/data")
            resp = await client.get("/data")
            assert resp.status_code == 429
            assert "Retry-After" in resp.headers
            assert int(resp.headers["Retry-After"]) >= 1

    async def test_health_endpoint_exempt(self) -> None:
        app = _make_limited_app(general_rate="1/minute")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(10):
                resp = await client.get("/health")
                assert resp.status_code == 200

    async def test_root_path_exempt(self) -> None:
        """Root path '/' is exempt from rate limiting (GAP-6: load balancer probe)."""
        app = FastAPI()
        settings = SautiRISSettings(
            rate_limit_enabled=True,
            rate_limit_general="1/minute",
            rate_limit_auth_endpoints="1/minute",
            rate_limit_apikey_create="1/minute",
            rate_limit_trusted_ips=[],
            database_url="sqlite+aiosqlite:///:memory:",
        )
        app.add_middleware(RateLimitMiddleware, settings=settings)

        @app.get("/")
        async def root() -> JSONResponse:
            return JSONResponse({"status": "ok"})

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(10):
                resp = await client.get("/")
                assert resp.status_code == 200

    async def test_disabled_rate_limiting(self) -> None:
        app = _make_limited_app(general_rate="1/minute", enabled=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(10):
                resp = await client.get("/data")
                assert resp.status_code == 200

    async def test_trusted_ip_bypasses_limit(self) -> None:
        app = FastAPI()
        settings = SautiRISSettings(
            rate_limit_enabled=True,
            rate_limit_general="1/minute",
            rate_limit_trusted_ips=["127.0.0.1", "testclient"],
            database_url="sqlite+aiosqlite:///:memory:",
        )
        app.add_middleware(RateLimitMiddleware, settings=settings)

        @app.get("/data")
        async def data() -> JSONResponse:
            return JSONResponse({"ok": True})

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(5):
                resp = await client.get("/data")
                assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GAP-7: _classify() endpoint classification unit tests
# ---------------------------------------------------------------------------


class TestRateLimitClassify:
    """Unit tests for RateLimitMiddleware._classify() route classification."""

    def _make_middleware(self) -> RateLimitMiddleware:
        settings = SautiRISSettings(
            rate_limit_enabled=True,
            rate_limit_general="100/minute",
            rate_limit_auth_endpoints="10/minute",
            rate_limit_apikey_create="5/minute",
            rate_limit_trusted_ips=[],
            database_url="sqlite+aiosqlite:///:memory:",
        )
        app = FastAPI()
        return RateLimitMiddleware(app, settings=settings)

    def test_auth_endpoint_uses_auth_rate_limit(self) -> None:
        """Paths containing /auth/ segment get auth rate limit."""
        mw = self._make_middleware()
        result = mw._classify("/api/v1/auth/token", "POST")
        assert result == "10/minute"

    def test_token_endpoint_uses_auth_rate_limit(self) -> None:
        """/token path gets auth rate limit."""
        mw = self._make_middleware()
        result = mw._classify("/api/v1/token", "POST")
        assert result == "10/minute"

    def test_apikey_create_uses_apikey_rate_limit(self) -> None:
        """POST /apikeys gets the dedicated API key creation rate limit."""
        mw = self._make_middleware()
        result = mw._classify("/api/v1/apikeys", "POST")
        assert result == "5/minute"

    def test_apikey_get_uses_general_rate_limit(self) -> None:
        """GET /apikeys (not POST) falls back to general rate limit."""
        mw = self._make_middleware()
        result = mw._classify("/api/v1/apikeys", "GET")
        assert result == "100/minute"

    def test_general_endpoint_uses_general_rate_limit(self) -> None:
        """Ordinary data endpoint uses the general rate limit."""
        mw = self._make_middleware()
        result = mw._classify("/api/v1/orders", "GET")
        assert result == "100/minute"

    def test_reports_endpoint_uses_general_rate_limit(self) -> None:
        """/reports is not a special endpoint — uses general rate."""
        mw = self._make_middleware()
        result = mw._classify("/api/v1/reports", "POST")
        assert result == "100/minute"


# ---------------------------------------------------------------------------
# GAP-M2: RateLimitMiddleware._parse_limit() — invalid period ValueError
# ---------------------------------------------------------------------------


class TestParseLimitUnit:
    """Unit tests for RateLimitMiddleware._parse_limit() static method."""

    def test_invalid_period_raises_value_error(self) -> None:
        """GAP-M2: An unsupported period like 'day' raises ValueError."""
        import pytest

        with pytest.raises(ValueError, match="Invalid rate limit period"):
            RateLimitMiddleware._parse_limit("100/day")

    def test_invalid_period_week_raises_value_error(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Invalid rate limit period"):
            RateLimitMiddleware._parse_limit("10/week")

    def test_valid_second(self) -> None:
        count, window = RateLimitMiddleware._parse_limit("10/second")
        assert count == 10
        assert window == 1

    def test_valid_minute(self) -> None:
        count, window = RateLimitMiddleware._parse_limit("100/minute")
        assert count == 100
        assert window == 60

    def test_valid_hour(self) -> None:
        count, window = RateLimitMiddleware._parse_limit("1000/hour")
        assert count == 1000
        assert window == 3600

    def test_plural_seconds_accepted(self) -> None:
        """'seconds' is accepted (trailing 's' stripped to 'second')."""
        count, window = RateLimitMiddleware._parse_limit("5/seconds")
        assert count == 5
        assert window == 1


# ---------------------------------------------------------------------------
# GAP-M3: RateLimitMiddleware._evict_stale_keys() — memory management
# ---------------------------------------------------------------------------


from sautiris.api.middleware.rate_limit import _MAX_WINDOW_KEYS  # noqa: E402


class TestEvictStaleKeys:
    """Unit tests for RateLimitMiddleware._evict_stale_keys()."""

    def _make_mw(self) -> RateLimitMiddleware:
        settings = SautiRISSettings(
            rate_limit_enabled=True,
            rate_limit_general="100/minute",
            rate_limit_auth_endpoints="10/minute",
            rate_limit_apikey_create="5/minute",
            rate_limit_trusted_ips=[],
            database_url="sqlite+aiosqlite:///:memory:",
        )
        return RateLimitMiddleware(FastAPI(), settings=settings)

    def test_evict_removes_all_empty_buckets_above_threshold(self) -> None:
        """GAP-M3a: All empty buckets are removed when len > _MAX_WINDOW_KEYS."""
        mw = self._make_mw()
        for i in range(_MAX_WINDOW_KEYS + 1):
            mw._windows[f"k{i}"] = []
        assert len(mw._windows) > _MAX_WINDOW_KEYS

        import time

        mw._evict_stale_keys(time.monotonic())

        assert len(mw._windows) == 0

    def test_evict_preserves_non_empty_buckets(self) -> None:
        """GAP-M3b: Non-empty (active) buckets survive eviction."""
        import time

        mw = self._make_mw()
        now = time.monotonic()
        for i in range(_MAX_WINDOW_KEYS + 1):
            mw._windows[f"k{i}"] = []
        mw._windows["active-1"] = [now]
        mw._windows["active-2"] = [now, now - 1]

        mw._evict_stale_keys(now)

        assert "active-1" in mw._windows
        assert "active-2" in mw._windows
        # All remaining buckets must be non-empty
        assert all(v for v in mw._windows.values())

    def test_no_eviction_below_threshold(self) -> None:
        """GAP-M3c: _evict_stale_keys is a no-op when len ≤ _MAX_WINDOW_KEYS."""
        import time

        mw = self._make_mw()
        # Add a handful of empty buckets (well below threshold)
        for i in range(10):
            mw._windows[f"k{i}"] = []
        initial_count = len(mw._windows)

        mw._evict_stale_keys(time.monotonic())

        # No change — below threshold
        assert len(mw._windows) == initial_count
