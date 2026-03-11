"""Tests for KeycloakAuthProvider.authenticate() — header extraction, JWT decoding,
tenant_id enforcement, key-miss refetch, and JWKS failure handling.

GAP-3: Keycloak authenticate() was completely untested.
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

from sautiris.core.auth.base import AuthUser
from sautiris.core.auth.keycloak import KeycloakAuthProvider


def _make_provider(
    ttl: int = 600,
    miss_interval: int = 60,
) -> KeycloakAuthProvider:
    return KeycloakAuthProvider(
        server_url="https://auth.example.com",
        realm="testrealm",
        client_id="ris-app",
        jwks_url="https://auth.example.com/realms/testrealm/certs",
        jwks_cache_ttl=ttl,
        jwks_key_miss_refetch_interval=miss_interval,
    )


def _make_request(authorization: str = "") -> Request:
    """Build a minimal Starlette Request with the given Authorization header."""
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
    """Construct a JWT payload dict with sensible defaults."""
    payload: dict[str, Any] = {
        "sub": sub or str(uuid.uuid4()),
        "preferred_username": "testuser",
        "email": "test@example.com",
        "name": "Test User",
        "realm_access": {"roles": roles or ["radiologist"]},
        "permissions": ["order:read"],
    }
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)
    return payload


def _prime_jwks_cache(provider: KeycloakAuthProvider) -> None:
    """Pre-populate the JWKS cache so authenticate() doesn't hit the network."""
    provider._jwks_cache = {"keys": [{"kid": "test-key", "kty": "RSA"}]}
    provider._cache_time = time.monotonic()


class TestKeycloakMissingHeader:
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
        """Basic auth scheme is not accepted → 401."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        request = _make_request(authorization="Basic dXNlcjpwYXNz")

        with pytest.raises(HTTPException) as exc_info:
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401


class TestKeycloakJwtErrors:
    """JWT decoding failures produce appropriate HTTP errors."""

    async def test_invalid_jwt_returns_401(self) -> None:
        """JWTError during decode (bad signature/expired) → 401."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        request = _make_request(authorization="Bearer invalid-jwt-token")

        with (
            patch("sautiris.core.auth.keycloak.jwt.decode", side_effect=JWTError("bad")),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401

    async def test_missing_tenant_id_claim_returns_401(self) -> None:
        """FIX-8 regression: token without tenant_id claim must be rejected → 401.

        Before the fix, the provider would silently default to DEFAULT_TENANT,
        giving unassigned tokens access to the wrong tenant.
        """
        provider = _make_provider()
        _prime_jwks_cache(provider)
        payload = _make_valid_payload(tenant_id=None)  # no tenant_id
        request = _make_request(authorization="Bearer fake-token")

        with (
            patch("sautiris.core.auth.keycloak.jwt.decode", return_value=payload),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401
        # #9: Generic user-facing message hides internal details;
        # server-side logging (auth.invalid_token) contains the reason.
        assert exc_info.value.detail == "Invalid or expired token"


class TestKeycloakValidJwt:
    """Happy-path authentication."""

    async def test_valid_jwt_returns_auth_user(self) -> None:
        """Well-formed JWT with tenant_id → AuthUser with correct fields."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_sub = str(uuid.uuid4())
        payload = _make_valid_payload(tenant_id=tenant_id, sub=user_sub, roles=["radiologist"])
        request = _make_request(authorization="Bearer real-token")

        with patch("sautiris.core.auth.keycloak.jwt.decode", return_value=payload):
            user = await provider.authenticate(request)

        assert str(user.user_id) == user_sub
        assert user.tenant_id == tenant_id
        assert "radiologist" in user.roles
        assert "order:read" in user.permissions


class TestKeycloakKeyMissRefetch:
    """Key-miss scenario triggers a one-shot JWKS refetch."""

    async def test_key_miss_triggers_jwks_refetch(self) -> None:
        """JWTError with 'key' in message triggers _get_jwks(force=True) refetch."""
        provider = _make_provider(miss_interval=0)  # no throttle
        _prime_jwks_cache(provider)
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_sub = str(uuid.uuid4())
        good_payload = _make_valid_payload(tenant_id=tenant_id, sub=user_sub)
        request = _make_request(authorization="Bearer some-token")

        call_count = 0

        def _decode_side_effect(token: str, jwks: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise JWTError("key not found in JWKS")  # triggers refetch
            return good_payload  # second call (after refetch) succeeds

        with patch("sautiris.core.auth.keycloak.jwt.decode", side_effect=_decode_side_effect):
            # Pre-populate so forced refetch has something to return
            new_jwks = {"keys": [{"kid": "new-key"}]}

            async def _fake_get_jwks(*, force: bool = False) -> dict[str, Any]:
                if force:
                    provider._jwks_cache = new_jwks
                return provider._jwks_cache or {}

            with patch.object(provider, "_get_jwks", side_effect=_fake_get_jwks):
                user = await provider.authenticate(request)

        assert str(user.user_id) == user_sub

    async def test_key_miss_with_failed_second_decode_returns_401(self) -> None:
        """Both decode attempts fail (key error) → 401 after fan-out completes."""
        provider = _make_provider(miss_interval=0)
        _prime_jwks_cache(provider)
        request = _make_request(authorization="Bearer bad-token")

        # Mock _get_jwks so the forced refetch returns without network access
        async def _fake_get_jwks(*, force: bool = False) -> dict[str, Any]:
            return provider._jwks_cache or {}

        # jwt.decode always raises JWTError with "key" in message
        # → triggers refetch → second decode also fails → 401
        with (
            patch("sautiris.core.auth.keycloak.jwt.decode", side_effect=JWTError("key error")),
            patch.object(provider, "_get_jwks", side_effect=_fake_get_jwks),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401


class TestKeycloakJwksFetchFailure:
    """JWKS fetch failures raise 503 Service Unavailable."""

    async def test_jwks_fetch_failure_returns_503(self) -> None:
        """HTTP error during JWKS fetch → 503 when cache is empty."""
        import httpx

        provider = _make_provider()
        # Don't prime the cache — simulate cold start
        provider._jwks_cache = None
        request = _make_request(authorization="Bearer some-token")

        # Mock the HTTP client to raise
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        provider._jwks_client = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await provider.authenticate(request)

        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# GAP-I2: check_permission — admin bypass and permission membership
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# #53: UUID validation — non-UUID sub and tenant_id must return 401
# ---------------------------------------------------------------------------


class TestKeycloakUUIDValidation:
    """#53: Non-UUID or missing sub/tenant_id claims must return 401.

    The providers must reject tokens where either claim is present but cannot
    be parsed as a valid UUID, to prevent privilege escalation via malformed
    claim injection.
    """

    async def test_non_uuid_sub_returns_401(self) -> None:
        """sub claim that is not a valid UUID → 401 (not a server error)."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        payload = _make_valid_payload(sub="not-a-uuid")
        request = _make_request(authorization="Bearer bad-sub-token")

        with (
            patch("sautiris.core.auth.keycloak.jwt.decode", return_value=payload),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired token"

    async def test_missing_sub_claim_returns_401(self) -> None:
        """Token with no 'sub' field → 401."""
        provider = _make_provider()
        _prime_jwks_cache(provider)
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        payload = _make_valid_payload(tenant_id=tenant_id)
        del payload["sub"]  # remove the sub claim entirely
        request = _make_request(authorization="Bearer no-sub-token")

        with (
            patch("sautiris.core.auth.keycloak.jwt.decode", return_value=payload),
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
        payload["tenant_id"] = "not-a-uuid-at-all"  # override with non-UUID
        request = _make_request(authorization="Bearer bad-tenant-token")

        with (
            patch("sautiris.core.auth.keycloak.jwt.decode", return_value=payload),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired token"


class TestKeycloakCheckPermission:
    """check_permission: permission-based check (base class behavior).

    The KeycloakAuthProvider now uses the base JWKSAuthProviderBase.check_permission
    which only checks user.permissions. Admin bypass was removed to centralise
    permission logic and prevent privilege escalation via role manipulation.
    """

    async def test_admin_role_does_not_bypass_permission_check(self) -> None:
        """User with 'admin' role but no permissions does NOT bypass the check.

        The base class check_permission checks only user.permissions.
        Role-based overrides should be handled at the request level, not here.
        """
        provider = _make_provider()
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        admin_user = AuthUser(
            user_id=uuid.uuid4(),
            username="admin",
            email="admin@example.com",
            tenant_id=tenant_id,
            roles=("admin",),
            permissions=(),  # no explicit permissions
            name="Admin User",
        )
        # Base class: no admin bypass — returns False when permission is missing
        assert await provider.check_permission(admin_user, "any:permission") is False

    async def test_non_admin_user_with_matching_permission_returns_true(self) -> None:
        """Non-admin user with the permission in their permissions tuple returns True."""
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

    async def test_non_admin_user_without_permission_returns_false(self) -> None:
        """Non-admin user missing a permission returns False (no bypass applies)."""
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

    async def test_admin_in_permissions_but_not_roles_does_not_bypass(self) -> None:
        """'admin' as a permission (not a role) does not trigger the bypass.

        The Keycloak provider checks ``'admin' in user.roles`` not
        ``'admin' in user.permissions``, so a user with 'admin' only in
        permissions should NOT get the unlimited bypass.
        """
        provider = _make_provider()
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user = AuthUser(
            user_id=uuid.uuid4(),
            username="fakeadmin",
            email="fake@example.com",
            tenant_id=tenant_id,
            roles=("regular",),  # 'admin' is NOT in roles
            permissions=("admin", "report:read"),
            name="Fake Admin",
        )
        # Bypass must not fire; only 'report:read' is a real permission here
        assert await provider.check_permission(user, "report:read") is True
        assert await provider.check_permission(user, "report:delete") is False
