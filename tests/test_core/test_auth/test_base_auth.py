"""Tests for AuthUser.__post_init__ list-to-tuple coercion (GAP-I1).

AuthUser is a frozen dataclass. The __post_init__ method coerces list
roles/permissions to tuples so the frozen invariant holds even when
callers pass mutable lists.
"""

from __future__ import annotations

import uuid

from sautiris.core.auth.base import AuthUser


def test_authuser_coerces_list_roles_to_tuple() -> None:
    """Passing a list for roles must yield a tuple after construction."""
    user = AuthUser(
        user_id=uuid.uuid4(),
        username="test",
        email="test@test.com",
        tenant_id=uuid.uuid4(),
        roles=["admin", "user"],  # type: ignore[arg-type]  # list, not tuple
        permissions=("read",),
        name="Test",
    )
    assert isinstance(user.roles, tuple)
    assert user.roles == ("admin", "user")


def test_authuser_coerces_list_permissions_to_tuple() -> None:
    """Passing a list for permissions must yield a tuple after construction."""
    user = AuthUser(
        user_id=uuid.uuid4(),
        username="test",
        email="test@test.com",
        tenant_id=uuid.uuid4(),
        roles=("admin",),
        permissions=["read", "write"],  # type: ignore[arg-type]  # list, not tuple
        name="Test",
    )
    assert isinstance(user.permissions, tuple)
    assert user.permissions == ("read", "write")


def test_authuser_coerces_both_lists_to_tuples() -> None:
    """Both roles and permissions as lists must both be coerced to tuples."""
    user = AuthUser(
        user_id=uuid.uuid4(),
        username="test",
        email="test@test.com",
        tenant_id=uuid.uuid4(),
        roles=["admin", "user"],  # type: ignore[arg-type]
        permissions=["read", "write"],  # type: ignore[arg-type]
        name="Test",
    )
    assert isinstance(user.roles, tuple)
    assert isinstance(user.permissions, tuple)
    assert user.roles == ("admin", "user")
    assert user.permissions == ("read", "write")


def test_authuser_tuples_remain_unchanged() -> None:
    """Tuples passed for roles/permissions must not be modified."""
    user = AuthUser(
        user_id=uuid.uuid4(),
        username="test",
        email="test@test.com",
        tenant_id=uuid.uuid4(),
        roles=("admin",),
        permissions=("read",),
        name="Test",
    )
    assert user.roles == ("admin",)
    assert user.permissions == ("read",)


def test_authuser_empty_list_roles_coerced_to_empty_tuple() -> None:
    """An empty list for roles must yield an empty tuple."""
    user = AuthUser(
        user_id=uuid.uuid4(),
        username="test",
        email="test@test.com",
        tenant_id=uuid.uuid4(),
        roles=[],  # type: ignore[arg-type]
        permissions=[],  # type: ignore[arg-type]
        name="Test",
    )
    assert user.roles == ()
    assert user.permissions == ()


def test_authuser_is_frozen_after_construction() -> None:
    """Frozen dataclass must raise on direct attribute assignment."""
    user = AuthUser(
        user_id=uuid.uuid4(),
        username="test",
        email="test@test.com",
        tenant_id=uuid.uuid4(),
        roles=("admin",),
        permissions=("read",),
        name="Test",
    )
    try:
        user.roles = ("hacker",)  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError was not raised")
    except Exception as exc:  # noqa: BLE001
        # dataclasses.FrozenInstanceError is the expected exception type
        assert "frozen" in str(type(exc).__name__).lower() or "cannot assign" in str(exc).lower()
