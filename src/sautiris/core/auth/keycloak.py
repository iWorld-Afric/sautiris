"""Keycloak OIDC authentication provider with JWKS TTL cache."""

from __future__ import annotations

import uuid

import structlog
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from sautiris.core.auth.base import AuthUser
from sautiris.core.auth.jwks_base import JWKSAuthProviderBase

logger = structlog.get_logger(__name__)

# Re-export for consumers that import MAX_STALE_AGE from this module
from sautiris.core.auth.jwks_base import MAX_STALE_AGE as MAX_STALE_AGE  # noqa: E402


class KeycloakAuthProvider(JWKSAuthProviderBase):
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
        resolved_jwks_url = jwks_url or (
            f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/certs"
        )
        self.issuer = f"{self.server_url}/realms/{self.realm}"
        super().__init__(
            jwks_url=resolved_jwks_url,
            cache_ttl=jwks_cache_ttl,
            key_miss_refetch_interval=jwks_key_miss_refetch_interval,
        )

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
                    # #9: Generic user-facing message; specifics logged server-side
                    self._log_token_error("jwt_error_after_refetch")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired token",
                    ) from None
            else:
                # #9: Generic user-facing message; specifics logged server-side
                self._log_token_error("jwt_error", exc_repr=repr(str(exc)[:128]))
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                ) from exc

        roles: list[str] = []
        realm_access = payload.get("realm_access", {})
        if isinstance(realm_access, dict):
            roles = realm_access.get("roles", [])

        # Reject tokens without tenant_id — defaulting silently gives
        # unassigned tokens access to the default production tenant.
        tenant_id_raw = payload.get("tenant_id")
        if tenant_id_raw is None:
            # #9/#12: truncate sub claim value in log
            self._log_token_error("missing_tenant_id_claim", sub=payload.get("sub", ""))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        sub_raw = payload.get("sub")
        if sub_raw is None:
            self._log_token_error("missing_sub_claim")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        try:
            user_id = uuid.UUID(str(sub_raw))
        except ValueError:
            self._log_token_error("invalid_sub_claim", sub=sub_raw)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from None

        tenant_uuid = self._parse_uuid(tenant_id_raw, "tenant_id")

        return AuthUser(
            user_id=user_id,
            username=payload.get("preferred_username", ""),
            email=payload.get("email", ""),
            tenant_id=tenant_uuid,
            roles=tuple(roles),
            permissions=tuple(payload.get("permissions", [])),
            name=payload.get("name", ""),
        )
