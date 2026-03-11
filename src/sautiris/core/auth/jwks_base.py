"""Shared JWKS cache base class for OIDC/OAuth2 authentication providers.

Extracts common logic from KeycloakAuthProvider and OAuth2AuthProvider:
- TTL cache with jitter (computed once at refresh time)
- asyncio.Lock for thundering-herd prevention
- Double-checked locking pattern
- Stale cache fallback (up to MAX_STALE_AGE seconds)
- Key-miss rate-limited forced refetch
- Centralised safe token-error logging (no raw JWT claim values in user-facing messages)
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from abc import abstractmethod
from typing import Any

import httpx
import structlog
from fastapi import HTTPException, Request, status

from sautiris.core.auth.base import AuthProvider, AuthUser

logger = structlog.get_logger(__name__)

# Maximum age (seconds) before a stale JWKS cache is considered too old to trust.
# After this duration, a fresh-fetch failure raises 503 instead of returning stale keys.
MAX_STALE_AGE: int = 86_400  # 24 hours


class JWKSAuthProviderBase(AuthProvider):
    """Base class for JWKS-backed JWT authentication providers.

    Handles all cache lifecycle logic; concrete subclasses only implement
    :meth:`authenticate` with provider-specific JWT decode and claim extraction.
    """

    def __init__(
        self,
        jwks_url: str,
        cache_ttl: int,
        key_miss_refetch_interval: int,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.jwks_url = jwks_url
        self._ttl: int = cache_ttl
        self._key_miss_interval: int = key_miss_refetch_interval
        # http_client is injectable for testing; created lazily if None
        self._jwks_client: httpx.AsyncClient | None = http_client
        self._jwks_cache: dict[str, Any] | None = None
        self._cache_time: float = 0.0
        self._last_key_miss_refetch: float = 0.0
        # Jitter is computed once at refresh time so it does not change per request
        self._effective_ttl: float = float(cache_ttl)
        # asyncio.Lock prevents thundering herd when cache expires
        self._jwks_lock: asyncio.Lock = asyncio.Lock()

    async def _get_jwks(self, *, force: bool = False) -> dict[str, Any]:
        """Return JWKS, fetching from the IdP if the cache is stale.

        Uses double-checked locking under an asyncio.Lock to prevent thundering
        herd: all concurrent callers that race on an expired cache wait for the
        first one to refresh, then reuse its result.

        Args:
            force: If True, bypass TTL and refetch immediately (key-miss scenario).
                   Rate-limited to one forced refetch per ``_key_miss_interval`` seconds.
        """
        now = time.monotonic()

        # Fast path — no lock needed for a fresh cache hit
        elapsed = now - self._cache_time
        cache_fresh = self._jwks_cache is not None and elapsed < self._effective_ttl
        if not force and cache_fresh:
            return self._jwks_cache  # type: ignore[return-value]

        if force and (now - self._last_key_miss_refetch) < self._key_miss_interval:
            logger.debug("jwks.key_miss_refetch_throttled")
            if self._jwks_cache is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication service unavailable — JWKS not yet loaded",
                )
            return self._jwks_cache

        async with self._jwks_lock:
            # Double-check after acquiring lock — another coroutine may have
            # already refreshed the cache while we waited
            now = time.monotonic()
            elapsed = now - self._cache_time
            cache_fresh = self._jwks_cache is not None and elapsed < self._effective_ttl
            if not force and cache_fresh:
                return self._jwks_cache  # type: ignore[return-value]

            if self._jwks_client is None:
                self._jwks_client = httpx.AsyncClient()

            try:
                resp = await self._jwks_client.get(self.jwks_url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("jwks.fetch_failed", url=self.jwks_url, error=str(exc))
                cache_age = now - self._cache_time
                if self._jwks_cache is not None and cache_age < MAX_STALE_AGE:
                    # #76: Log at error level when falling back to stale cache
                    logger.error(
                        "jwks.using_stale_cache",
                        url=self.jwks_url,
                        cache_age_seconds=round(cache_age, 1),
                    )
                    return self._jwks_cache
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication service unavailable",
                ) from exc

            self._jwks_cache = resp.json()
            self._cache_time = now
            # Compute jitter once at refresh time — not re-rolled on every request
            self._effective_ttl = self._ttl - random.uniform(0, self._ttl * 0.1)
            if force:
                self._last_key_miss_refetch = now
            logger.debug("jwks.refreshed", forced=force)
            return self._jwks_cache

    def _parse_uuid(self, value: Any, field_name: str) -> uuid.UUID:
        """Parse *value* to a UUID, raising 401 with a safe message on failure.

        Logs the actual invalid value server-side; never exposes it to the caller.
        """
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            logger.warning(
                "auth.invalid_uuid_claim",
                field=field_name,
                value_repr=repr(str(value)[:64]),
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from None

    def _log_token_error(self, reason: str, **extra: object) -> None:
        """Log a token validation failure server-side with truncated claim values.

        Never surfaces raw JWT claim values in user-facing errors — only in the
        server log (finding #12).
        """
        logger.warning(
            "auth.invalid_token",
            reason=reason,
            **{k: repr(str(v)[:64]) for k, v in extra.items()},
        )

    @abstractmethod
    async def authenticate(self, request: Request) -> AuthUser:
        """Validate the bearer token and return an AuthUser."""

    async def get_current_user(self, request: Request) -> AuthUser:
        return await self.authenticate(request)

    async def close(self) -> None:
        """Close the underlying JWKS HTTP client."""
        if self._jwks_client is not None:
            await self._jwks_client.aclose()

    async def check_permission(self, user: AuthUser, permission: str) -> bool:
        return permission in user.permissions
