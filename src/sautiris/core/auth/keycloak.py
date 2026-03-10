"""Keycloak OIDC authentication provider with JWKS TTL cache."""

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


class KeycloakAuthProvider(AuthProvider):
    """Keycloak OIDC token verification via JWKS with TTL cache and key-miss refetch."""

    def __init__(
        self,
        server_url: str,
        realm: str,
        client_id: str,
        jwks_url: str = "",
        *,
        jwks_cache_ttl: int = 600,
        jwks_key_miss_refetch_interval: int = 60,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.jwks_url = jwks_url or (
            f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/certs"
        )
        self.issuer = f"{self.server_url}/realms/{self.realm}"
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
        """Return JWKS, fetching from Keycloak if the cache is stale.

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

    def _extract_token(self, request: Request) -> str:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
            )
        return auth_header[7:]

    async def authenticate(self, request: Request) -> AuthUser:
        token = self._extract_token(request)
        jwks = await self._get_jwks()
        try:
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
            )
        except JWTError as exc:
            exc_str = str(exc).lower()
            if "key" in exc_str or "kid" in exc_str:
                # Unknown key — try a one-shot JWKS refresh (key rotation scenario)
                logger.warning("jwks.key_miss_attempting_refetch")
                jwks = await self._get_jwks(force=True)
                try:
                    payload = jwt.decode(
                        token,
                        jwks,
                        algorithms=["RS256"],
                        audience=self.client_id,
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

        roles: list[str] = []
        realm_access = payload.get("realm_access", {})
        if isinstance(realm_access, dict):
            roles = realm_access.get("roles", [])

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
            username=payload.get("preferred_username", ""),
            email=payload.get("email", ""),
            tenant_id=uuid.UUID(str(tenant_id_raw)),
            roles=tuple(roles),
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
        return permission in user.permissions or "admin" in user.roles
