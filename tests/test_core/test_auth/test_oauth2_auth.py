"""Tests for OAuth2AuthProvider.authenticate() — header extraction, JWT decoding,
tenant_id enforcement, key-miss refetch, and JWKS failure handling.

GAP-3: OAuth2 authenticate() was completely untested.
FIX-8 regression: missing tenant_id claim must return 401 (not default tenant).
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from jose import JWTError
from starlette.requests import Request

from sautiris.core.auth.oauth2 import OAuth2AuthProvider


def _make_provider(
    ttl: int = 600,
    miss_interval: int = 60,
) -> OAuth2AuthProvider:
    return OAuth2AuthProvider(
        jwks_url="https://idp.example.com/.well-known/jwks.json",
        issuer="https://idp.example.com",
        audience="my-ris",
        jwks_cache_ttl=ttl,
        jwks_key_miss_refetch_interval=miss_interval,
    )


def _make_request(authorization: str = "") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": headers,
    }
    return Request(scope)


def _make_valid_payload(
    *,
    tenant_id: uuid.UUID | None = uuid.UUID("00000000-0000-0000-0000-000000000001"),
    sub: str | None = None,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sub": sub or str(uuid.uuid4()),
        "preferred_username": "oauthuser",
        "email": "oauth@example.com",
        "name": "OAuth User",
        "roles": roles or ["radiologist"],
        "permissions": ["order:read", "report:read"],
    }
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)
    return payload


def _prime_jwks_cache(provider: OAuth2AuthProvider) -> None:
    provider._jwks_cache = {"keys": [{"kid": "oauth-key", "kty": "RSA"}]}
    provider._cache_time = time.monotonic()


class TestOAuth2MissingHeader:
    """Authentication fails when Authorization header is absent or malformed."""

    async def test_missing_authorization_header_returns_401(self) -> None:
        """No Authorization header → 401."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        request = _make_request(authorization="")

        with pytest.raises(HTTPException) as exc_info:
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401

    async def test_non_bearer_scheme_returns_401(self) -> None:
        """Non-Bearer scheme → 401."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        request = _make_request(authorization="ApiKey my-key-here")

        with pytest.raises(HTTPException) as exc_info:
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401


class TestOAuth2JwtErrors:
    """JWT decoding failures produce appropriate HTTP errors."""

    async def test_invalid_jwt_returns_401(self) -> None:
        """JWTError during decode → 401."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        request = _make_request(authorization="Bearer not-a-real-jwt")

        with (
            patch("sautiris.core.auth.oauth2.jwt.decode", side_effect=JWTError("invalid")),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401

    async def test_missing_tenant_id_claim_returns_401(self) -> None:
        """FIX-8 regression: token without tenant_id → 401 (not default tenant access)."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        payload = _make_valid_payload(tenant_id=None)
        request = _make_request(authorization="Bearer tenant-less-token")

        with (
            patch("sautiris.core.auth.oauth2.jwt.decode", return_value=payload),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401
        # #9: Generic user-facing message hides internal details;
        # server-side logging (auth.invalid_token) contains the reason.
        assert exc_info.value.detail == "Invalid or expired token"


class TestOAuth2ValidJwt:
    """Happy-path authentication."""

    async def test_valid_jwt_returns_auth_user(self) -> None:
        """Well-formed JWT with tenant_id → AuthUser with correct fields."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_sub = str(uuid.uuid4())
        payload = _make_valid_payload(tenant_id=tenant_id, sub=user_sub)
        request = _make_request(authorization="Bearer valid-token")

        with patch("sautiris.core.auth.oauth2.jwt.decode", return_value=payload):
            user = await provider.authenticate(request)

        assert str(user.user_id) == user_sub
        assert user.tenant_id == tenant_id
        assert "radiologist" in user.roles


class TestOAuth2KeyMissRefetch:
    """Key-miss triggers a one-shot JWKS refetch."""

    async def test_key_miss_triggers_jwks_refetch(self) -> None:
        """JWTError with 'key' in message triggers _get_jwks(force=True) refetch."""
        provider = _make_provider(miss_interval=0)
        _prime_jwks_cache(provider)
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_sub = str(uuid.uuid4())
        good_payload = _make_valid_payload(tenant_id=tenant_id, sub=user_sub)
        request = _make_request(authorization="Bearer key-miss-token")

        call_count = 0

        def _decode_side_effect(token: str, jwks: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise JWTError("unknown kid: missing key")
            return good_payload

        new_jwks = {"keys": [{"kid": "rotated-key"}]}

        async def _fake_get_jwks(*, force: bool = False) -> dict[str, Any]:
            if force:
                provider._jwks_cache = new_jwks
            return provider._jwks_cache or {}

        with (
            patch("sautiris.core.auth.oauth2.jwt.decode", side_effect=_decode_side_effect),
            patch.object(provider, "_get_jwks", side_effect=_fake_get_jwks),
        ):
            user = await provider.authenticate(request)

        assert str(user.user_id) == user_sub


class TestOAuth2JwksFetchFailure:
    """JWKS fetch failures raise 503."""

    async def test_jwks_fetch_failure_returns_503(self) -> None:
        """HTTP error on JWKS fetch → 503 Service Unavailable."""
        import httpx

        provider = _make_provider()
        provider._jwks_cache = None  # cold start
        request = _make_request(authorization="Bearer some-token")

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout", request=None)
        provider._jwks_client = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await provider.authenticate(request)

        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# GAP-I2: check_permission — OAuth2 has NO admin bypass (contrast with Keycloak)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# #53: UUID validation — non-UUID sub and tenant_id must return 401
# ---------------------------------------------------------------------------


class TestOAuth2UUIDValidation:
    """#53: Non-UUID or missing sub/tenant_id claims must return 401.

    OAuth2AuthProvider uses the same _parse_uuid helper from JWKSAuthProviderBase,
    so these tests verify the shared behaviour is wired correctly.
    """

    async def test_non_uuid_sub_returns_401(self) -> None:
        """sub claim that is not a valid UUID → 401 (not a server error)."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        payload = _make_valid_payload(sub="not-a-valid-uuid-string")
        request = _make_request(authorization="Bearer bad-sub-token")

        with (
            patch("sautiris.core.auth.oauth2.jwt.decode", return_value=payload),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired token"

    async def test_missing_sub_claim_returns_401(self) -> None:
        """Token with no 'sub' field → 401."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        payload = _make_valid_payload()
        del payload["sub"]
        request = _make_request(authorization="Bearer no-sub-token")

        with (
            patch("sautiris.core.auth.oauth2.jwt.decode", return_value=payload),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired token"

    async def test_non_uuid_tenant_id_returns_401(self) -> None:
        """tenant_id claim that is not a valid UUID → 401."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        payload = _make_valid_payload()
        payload["tenant_id"] = "totally-not-a-uuid"
        request = _make_request(authorization="Bearer bad-tenant-token")

        with (
            patch("sautiris.core.auth.oauth2.jwt.decode", return_value=payload),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired token"


class TestOAuth2CheckPermission:
    """check_permission: OAuth2 provider checks permissions tuple only, no admin bypass.

    Unlike KeycloakAuthProvider (which short-circuits on 'admin' in roles),
    OAuth2AuthProvider.check_permission only checks ``permission in user.permissions``.
    This verifies the design difference is enforced.
    """

    async def test_user_with_permission_returns_true(self) -> None:
        """User whose permissions tuple contains the queried permission returns True."""
        from sautiris.core.auth.base import AuthUser

        provider = _make_provider()
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user = AuthUser(
            user_id=uuid.uuid4(),
            username="radiologist",
            email="rad@example.com",
            tenant_id=tenant_id,
            roles=("radiologist",),
            permissions=("report:read", "order:read"),
            name="Radiologist",
        )
        assert await provider.check_permission(user, "report:read") is True

    async def test_user_without_permission_returns_false(self) -> None:
        """User whose permissions tuple does NOT contain the queried permission returns False."""
        from sautiris.core.auth.base import AuthUser

        provider = _make_provider()
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user = AuthUser(
            user_id=uuid.uuid4(),
            username="radiologist",
            email="rad@example.com",
            tenant_id=tenant_id,
            roles=("radiologist",),
            permissions=("report:read",),
            name="Radiologist",
        )
        assert await provider.check_permission(user, "admin:manage") is False

    async def test_admin_role_does_not_bypass_permission_check(self) -> None:
        """OAuth2 provider does NOT have admin bypass — 'admin' in roles is irrelevant.

        This is the key behavioral difference from KeycloakAuthProvider.
        If a user has 'admin' in roles but not the permission, check returns False.
        """
        from sautiris.core.auth.base import AuthUser

        provider = _make_provider()
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        admin_user = AuthUser(
            user_id=uuid.uuid4(),
            username="admin",
            email="admin@example.com",
            tenant_id=tenant_id,
            roles=("admin",),  # has admin role
            permissions=(),  # but NO permissions
            name="Admin User",
        )
        # OAuth2 provider has no bypass: 'admin' in roles does NOT grant all permissions
        result = await provider.check_permission(admin_user, "any:permission")
        assert result is False
