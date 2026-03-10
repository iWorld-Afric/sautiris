"""RBAC permission system for SautiRIS."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum


class Permission(StrEnum):
    """All permissions in SautiRIS."""

    # Orders
    ORDER_CREATE = "order:create"
    ORDER_READ = "order:read"
    ORDER_UPDATE = "order:update"
    ORDER_CANCEL = "order:cancel"

    # Schedule
    SCHEDULE_READ = "schedule:read"
    SCHEDULE_MANAGE = "schedule:manage"

    # Worklist
    WORKLIST_READ = "worklist:read"
    WORKLIST_UPDATE = "worklist:update"

    # Reports
    REPORT_CREATE = "report:create"
    REPORT_READ = "report:read"
    REPORT_UPDATE = "report:update"
    REPORT_FINALIZE = "report:finalize"
    REPORT_AMEND = "report:amend"

    # Billing
    BILLING_READ = "billing:read"
    BILLING_MANAGE = "billing:manage"

    # Dose
    DOSE_READ = "dose:read"
    DOSE_RECORD = "dose:record"

    # Peer Review
    PEER_REVIEW_CREATE = "peer_review:create"
    PEER_REVIEW_READ = "peer_review:read"

    # Alerts
    ALERT_CREATE = "alert:create"
    ALERT_READ = "alert:read"
    ALERT_ACKNOWLEDGE = "alert:acknowledge"

    # Analytics
    ANALYTICS_READ = "analytics:read"

    # Admin
    ADMIN_FULL = "admin:full"


ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "radiologist": {
        Permission.ORDER_READ,
        Permission.ORDER_UPDATE,
        Permission.WORKLIST_READ,
        Permission.REPORT_CREATE,
        Permission.REPORT_READ,
        Permission.REPORT_UPDATE,
        Permission.REPORT_FINALIZE,
        Permission.REPORT_AMEND,
        Permission.DOSE_READ,
        Permission.PEER_REVIEW_CREATE,
        Permission.PEER_REVIEW_READ,
        Permission.ALERT_CREATE,
        Permission.ALERT_READ,
        Permission.ALERT_ACKNOWLEDGE,
        Permission.ANALYTICS_READ,
    },
    "technologist": {
        Permission.ORDER_READ,
        Permission.SCHEDULE_READ,
        Permission.WORKLIST_READ,
        Permission.WORKLIST_UPDATE,
        Permission.DOSE_READ,
        Permission.DOSE_RECORD,
    },
    "referring_physician": {
        Permission.ORDER_CREATE,
        Permission.ORDER_READ,
        Permission.REPORT_READ,
        Permission.ALERT_READ,
        Permission.ALERT_ACKNOWLEDGE,
    },
    "clerk": {
        Permission.ORDER_CREATE,
        Permission.ORDER_READ,
        Permission.ORDER_UPDATE,
        Permission.SCHEDULE_READ,
        Permission.SCHEDULE_MANAGE,
        Permission.BILLING_READ,
        Permission.BILLING_MANAGE,
    },
    "admin": {
        Permission.ADMIN_FULL,
        *Permission,
    },
}


def get_permissions_for_roles(roles: Sequence[str]) -> set[Permission]:
    """Gather all permissions granted by the user's roles."""
    perms: set[Permission] = set()
    for role in roles:
        role_perms = ROLE_PERMISSIONS.get(role)
        if role_perms is not None:
            perms |= role_perms
    return perms


def has_permission(roles: Sequence[str], permission: Permission) -> bool:
    """Check if any of the given roles grants the specified permission."""
    return permission in get_permissions_for_roles(roles)
