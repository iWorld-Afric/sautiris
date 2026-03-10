"""Generic OAuth2 bearer token provider with JWKS TTL cache."""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from typing import Any

import httpx
import structlog
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from sautiris.core.auth.base import AuthProvider, AuthUser

logger = structlog.get_logger(__name__)


class OAuth2AuthProvider(AuthProvider):
    """Generic OAuth2 bearer token verification via JWKS with TTL cache and key-miss refetch."""

    def __init__(
        self,
        jwks_url: str,
        issuer: str,
        audience: str,
        *,
        jwks_cache_ttl: int = 600,
        jwks_key_miss_refetch_interval: int = 60,
    ) -> None:
        self.jwks_url = jwks_url
        self.issuer = issuer
        self.audience = audience
        self._jwks_client: httpx.AsyncClient | None = None
        self._jwks_cache: dict[str, Any] | None = None
        self._cache_time: float = 0.0
        self._last_key_miss_refetch: float = 0.0
        self._ttl: int = jwks_cache_ttl
        self._key_miss_interval: int = jwks_key_miss_refetch_interval
        # Jitter is fixed at refresh time (not re-rolled per request) — FIX-7
        self._effective_ttl: float = float(jwks_cache_ttl)
        # asyncio.Lock prevents thundering herd when cache expires — FIX-5
        self._jwks_lock: asyncio.Lock = asyncio.Lock()

    async def _get_jwks(self, *, force: bool = False) -> dict[str, Any]:
        """Return JWKS, fetching from the IdP if the cache is stale.

        Uses a double-check pattern under an asyncio.Lock to prevent thundering
        herd: all concurrent callers that race on an expired cache wait for the
        first one to refresh, then reuse its result (FIX-5).

        Jitter is computed once at refresh time and stored as ``_effective_ttl``
        so it does not change on every auth request (FIX-7).

        Args:
            force: If True, bypass TTL and refetch immediately (key-miss scenario).
                   Rate-limited to one forced refetch per ``_key_miss_interval`` seconds.
        """
        now = time.monotonic()

        # Fast path — no lock needed for a cache hit
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
            # already refreshed the cache while we waited (prevents thundering herd)
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
                # SEC-2: Return stale cache if available — only raise 503 on cold start
                if self._jwks_cache is not None:
                    logger.warning(
                        "jwks.using_stale_cache",
                        url=self.jwks_url,
                        cache_age_seconds=round(now - self._cache_time, 1),
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
            if self._jwks_cache is None:
                raise RuntimeError("JWKS cache is None after successful fetch")
            return self._jwks_cache

    async def authenticate(self, request: Request) -> AuthUser:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
            )
        token = auth_header[7:]
        jwks = await self._get_jwks()
        try:
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
        except JWTError as exc:
            exc_str = str(exc).lower()
            if "key" in exc_str or "kid" in exc_str:
                logger.warning("jwks.key_miss_attempting_refetch")
                jwks = await self._get_jwks(force=True)
                try:
                    payload = jwt.decode(
                        token,
                        jwks,
                        algorithms=["RS256"],
                        audience=self.audience,
                        issuer=self.issuer,
                    )
                except JWTError:
                    logger.warning("auth.jwt_error_after_refetch", exc_info=True)
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired token",
                    ) from None
            else:
                logger.warning("auth.jwt_error", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                ) from exc

        # FIX-8: Reject tokens without tenant_id — defaulting silently gives
        # unassigned tokens access to the default production tenant.
        tenant_id_raw = payload.get("tenant_id")
        if tenant_id_raw is None:
            logger.warning("auth.missing_tenant_id_claim", sub=payload.get("sub"))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing required tenant_id claim",
            )
        return AuthUser(
            user_id=uuid.UUID(payload["sub"]),
            username=payload.get("preferred_username", payload.get("sub", "")),
            email=payload.get("email", ""),
            tenant_id=uuid.UUID(str(tenant_id_raw)),
            roles=tuple(payload.get("roles", [])),
            permissions=tuple(payload.get("permissions", [])),
            name=payload.get("name", ""),
        )

    async def get_current_user(self, request: Request) -> AuthUser:
        return await self.authenticate(request)

    async def close(self) -> None:
        """Close the underlying JWKS HTTP client."""
        if self._jwks_client is not None:
            await self._jwks_client.aclose()

    async def check_permission(self, user: AuthUser, permission: str) -> bool:
        return permission in user.permissions
