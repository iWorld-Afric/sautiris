"""Sliding-window rate limiting middleware.

Uses an in-memory bucket per (IP, rate-tier) key.  Optional Redis backend can be
added in a future iteration.  The health endpoint is always exempt.

Rates are configured in ``SautiRISSettings``:
    - ``rate_limit_general``: applied to all non-special endpoints (default 100/minute)
    - ``rate_limit_auth_endpoints``: applied to auth/token paths (default 10/minute)
    - ``rate_limit_apikey_create``: applied to POST /apikeys (default 5/minute)
    - ``rate_limit_trusted_ips``: list of IPs that bypass rate limiting
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from sautiris.config import SautiRISSettings

logger = structlog.get_logger(__name__)

_HEALTH_SUFFIXES = ("/health", "/healthz", "/readyz", "/livez")
_AUTH_SEGMENTS = ("/token", "/auth/", "/login", "/logout", "/refresh")

# Evict stale window keys when the dict exceeds this size to bound memory usage.
_MAX_WINDOW_KEYS = 10_000


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-process sliding-window rate limiter."""

    def __init__(self, app: object, settings: SautiRISSettings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings
        self._lock = asyncio.Lock()  # asyncio.Lock — safe in async dispatch()
        self._windows: dict[str, list[float]] = defaultdict(list)
        # FIX-5: Validate all rate limit config values at startup to catch
        # misconfigured periods (e.g. "100/day") before they crash at request time.
        for _rate_cfg in (
            settings.rate_limit_general,
            settings.rate_limit_auth_endpoints,
            settings.rate_limit_apikey_create,
        ):
            self._parse_limit(_rate_cfg)

    @staticmethod
    def _parse_limit(rate: str) -> tuple[int, int]:
        """Parse ``'100/minute'`` → ``(100, 60)``.

        Raises:
            ValueError: If the period is not one of second/minute/hour.
        """
        count_str, period = rate.split("/")
        windows = {"second": 1, "minute": 60, "hour": 3600}
        period_key = period.lower().rstrip("s")
        if period_key not in windows:
            raise ValueError(
                f"Invalid rate limit period '{period}' in '{rate}'. "
                "Supported values: second, minute, hour."
            )
        return int(count_str), windows[period_key]

    def _evict_stale_keys(self) -> None:
        """Prune empty window buckets when the dict grows beyond threshold.

        Called while holding ``_lock``.  Only scans when len > _MAX_WINDOW_KEYS
        so the amortised cost is negligible under normal traffic.
        """
        if len(self._windows) <= _MAX_WINDOW_KEYS:
            return
        stale = [k for k, bucket in self._windows.items() if not bucket]
        for k in stale:
            del self._windows[k]

    def _classify(self, path: str, method: str) -> str:
        if "/apikeys" in path and method == "POST":
            return self._settings.rate_limit_apikey_create
        if any(seg in path for seg in _AUTH_SEGMENTS):
            return self._settings.rate_limit_auth_endpoints
        return self._settings.rate_limit_general

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._settings.rate_limit_enabled:
            return await call_next(request)

        path = request.url.path
        if any(path.endswith(s) for s in _HEALTH_SUFFIXES) or path == "/":
            return await call_next(request)

        if request.client is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "Unable to determine client address"},
            )
        client_ip = request.client.host
        if client_ip in self._settings.rate_limit_trusted_ips:
            return await call_next(request)

        rate_str = self._classify(path, request.method)
        max_count, window_secs = self._parse_limit(rate_str)
        key = f"{client_ip}:{rate_str}"
        now = time.monotonic()
        cutoff = now - window_secs

        async with self._lock:
            bucket = self._windows[key]
            self._windows[key] = bucket = [t for t in bucket if t > cutoff]
            if len(bucket) >= max_count:
                oldest = bucket[0]
                retry_after = max(1, int(window_secs - (now - oldest)) + 1)
                logger.warning(
                    "rate_limit_exceeded",
                    ip=client_ip,
                    path=path,
                    limit=rate_str,
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please retry later."},
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)
            self._evict_stale_keys()

        return await call_next(request)
