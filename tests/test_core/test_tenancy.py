"""Tests for multi-tenancy context and middleware."""

from __future__ import annotations

import uuid

from sautiris.core.tenancy import (
    DEFAULT_TENANT,
    get_current_tenant_id,
    set_current_tenant_id,
)


def test_default_tenant() -> None:
    set_current_tenant_id(DEFAULT_TENANT)
    assert get_current_tenant_id() == DEFAULT_TENANT


def test_set_and_get_tenant() -> None:
    custom = uuid.uuid4()
    set_current_tenant_id(custom)
    assert get_current_tenant_id() == custom
    # Reset
    set_current_tenant_id(DEFAULT_TENANT)


def test_default_tenant_value() -> None:
    assert uuid.UUID("00000000-0000-0000-0000-000000000001") == DEFAULT_TENANT
