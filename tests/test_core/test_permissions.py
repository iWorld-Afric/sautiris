"""Tests for the RBAC permission system."""

from __future__ import annotations

from sautiris.core.permissions import (
    Permission,
    get_permissions_for_roles,
    has_permission,
)


def test_radiologist_has_report_create() -> None:
    assert has_permission(["radiologist"], Permission.REPORT_CREATE)


def test_radiologist_cannot_manage_schedule() -> None:
    assert not has_permission(["radiologist"], Permission.SCHEDULE_MANAGE)


def test_clerk_has_schedule_manage() -> None:
    assert has_permission(["clerk"], Permission.SCHEDULE_MANAGE)


def test_admin_has_all_permissions() -> None:
    perms = get_permissions_for_roles(["admin"])
    for p in Permission:
        assert p in perms


def test_technologist_has_worklist_update() -> None:
    assert has_permission(["technologist"], Permission.WORKLIST_UPDATE)


def test_unknown_role_has_no_permissions() -> None:
    perms = get_permissions_for_roles(["nonexistent_role"])
    assert len(perms) == 0


def test_multiple_roles_combine() -> None:
    perms = get_permissions_for_roles(["radiologist", "clerk"])
    assert Permission.REPORT_CREATE in perms
    assert Permission.BILLING_MANAGE in perms
