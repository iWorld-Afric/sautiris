"""Keycloak OIDC authentication provider."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from sautiris.core.auth.base import AuthProvider, AuthUser


class KeycloakAuthProvider(AuthProvider):
    """Keycloak OIDC token verification via JWKS."""

    def __init__(
        self,
        server_url: str,
        realm: str,
        client_id: str,
        jwks_url: str = "",
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

    async def _get_jwks(self) -> dict[str, Any]:
        if self._jwks_cache is not None:
            return self._jwks_cache
        if self._jwks_client is None:
            self._jwks_client = httpx.AsyncClient()
        resp = await self._jwks_client.get(self.jwks_url)
        resp.raise_for_status()
        self._jwks_cache = resp.json()
        assert self._jwks_cache is not None
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token verification failed: {exc}",
            ) from exc

        roles: list[str] = []
        realm_access = payload.get("realm_access", {})
        if isinstance(realm_access, dict):
            roles = realm_access.get("roles", [])

        tenant_id_raw = payload.get("tenant_id", "00000000-0000-0000-0000-000000000001")
        return AuthUser(
            user_id=uuid.UUID(payload["sub"]),
            username=payload.get("preferred_username", ""),
            email=payload.get("email", ""),
            tenant_id=uuid.UUID(str(tenant_id_raw)),
            roles=roles,
            permissions=payload.get("permissions", []),
            name=payload.get("name", ""),
        )

    async def get_current_user(self, request: Request) -> AuthUser:
        return await self.authenticate(request)

    async def check_permission(self, user: AuthUser, permission: str) -> bool:
        return permission in user.permissions or "admin" in user.roles
