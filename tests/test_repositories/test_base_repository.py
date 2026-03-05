"""Tests for TenantAwareRepository base."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.tenancy import set_current_tenant_id
from sautiris.models.order import RadiologyOrder
from sautiris.repositories.base import TenantAwareRepository

TEST_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")


class OrderRepository(TenantAwareRepository[RadiologyOrder]):
    model = RadiologyOrder


@pytest.mark.asyncio
async def test_create_and_get(db_session: AsyncSession) -> None:
    repo = OrderRepository(db_session)
    order = RadiologyOrder(
        patient_id=uuid.uuid4(),
        accession_number=f"ACC-{uuid.uuid4().hex[:8]}",
        modality="CT",
    )
    created = await repo.create(order)
    assert created.tenant_id == TEST_TENANT

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.accession_number == order.accession_number


@pytest.mark.asyncio
async def test_list_all(db_session: AsyncSession) -> None:
    repo = OrderRepository(db_session)
    for _ in range(3):
        order = RadiologyOrder(
            patient_id=uuid.uuid4(),
            accession_number=f"ACC-{uuid.uuid4().hex[:8]}",
            modality="CR",
        )
        await repo.create(order)

    orders = await repo.list_all()
    assert len(orders) == 3


@pytest.mark.asyncio
async def test_tenant_isolation(db_session: AsyncSession) -> None:
    repo = OrderRepository(db_session)
    order = RadiologyOrder(
        patient_id=uuid.uuid4(),
        accession_number=f"ACC-{uuid.uuid4().hex[:8]}",
        modality="MR",
    )
    created = await repo.create(order)

    # Switch to different tenant
    set_current_tenant_id(OTHER_TENANT)
    fetched = await repo.get_by_id(created.id)
    assert fetched is None

    # Switch back
    set_current_tenant_id(TEST_TENANT)
    fetched = await repo.get_by_id(created.id)
    assert fetched is not None


@pytest.mark.asyncio
async def test_delete(db_session: AsyncSession) -> None:
    repo = OrderRepository(db_session)
    order = RadiologyOrder(
        patient_id=uuid.uuid4(),
        accession_number=f"ACC-{uuid.uuid4().hex[:8]}",
        modality="US",
    )
    created = await repo.create(order)
    await repo.delete(created)

    fetched = await repo.get_by_id(created.id)
    assert fetched is None
