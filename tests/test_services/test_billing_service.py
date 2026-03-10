"""Tests for BillingService."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.billing import BillingCode
from sautiris.services.billing_service import (
    BillingAssignmentNotFoundError,
    BillingCodeInactiveError,
    BillingCodeNotFoundError,
    BillingService,
    DuplicateBillingAssignmentError,
)
from tests.conftest import TEST_USER_ID


async def _create_billing_code(
    session: AsyncSession,
    *,
    code: str = "71046",
    display: str = "Chest X-ray, 2 views",
    code_system: str = "CPT",
    is_active: bool = True,
) -> BillingCode:
    bc = BillingCode(
        id=uuid.uuid4(),
        code_system=code_system,
        code=code,
        display=display,
        is_active=is_active,
    )
    session.add(bc)
    await session.flush()
    return bc


@pytest.fixture
def billing_service(db_session: AsyncSession) -> BillingService:
    return BillingService(db_session)


async def test_assign_code(billing_service: BillingService, db_session: AsyncSession) -> None:
    code = await _create_billing_code(db_session)
    order_id = uuid.uuid4()
    assignment = await billing_service.assign_code(
        order_id=order_id,
        billing_code_id=code.id,
        assigned_by=TEST_USER_ID,
    )
    assert assignment.order_id == order_id
    assert assignment.billing_code_id == code.id
    assert assignment.quantity == 1


async def test_assign_nonexistent_code(billing_service: BillingService) -> None:
    with pytest.raises(BillingCodeNotFoundError):
        await billing_service.assign_code(
            order_id=uuid.uuid4(),
            billing_code_id=uuid.uuid4(),
        )


async def test_assign_inactive_code(
    billing_service: BillingService, db_session: AsyncSession
) -> None:
    code = await _create_billing_code(db_session, is_active=False)
    with pytest.raises(BillingCodeInactiveError):
        await billing_service.assign_code(
            order_id=uuid.uuid4(),
            billing_code_id=code.id,
        )


async def test_assign_duplicate(billing_service: BillingService, db_session: AsyncSession) -> None:
    code = await _create_billing_code(db_session)
    order_id = uuid.uuid4()
    await billing_service.assign_code(order_id=order_id, billing_code_id=code.id)
    with pytest.raises(DuplicateBillingAssignmentError):
        await billing_service.assign_code(order_id=order_id, billing_code_id=code.id)


async def test_get_order_billing(billing_service: BillingService, db_session: AsyncSession) -> None:
    code = await _create_billing_code(db_session)
    order_id = uuid.uuid4()
    await billing_service.assign_code(order_id=order_id, billing_code_id=code.id)
    items = await billing_service.get_order_billing(order_id)
    assert len(items) == 1


async def test_search_codes(billing_service: BillingService, db_session: AsyncSession) -> None:
    await _create_billing_code(db_session, code="71046", display="Chest X-ray")
    await _create_billing_code(db_session, code="74177", display="CT Abdomen with contrast")
    results = await billing_service.search_codes(q="Chest")
    assert len(results) == 1
    assert results[0].code == "71046"


async def test_remove_assignment(billing_service: BillingService, db_session: AsyncSession) -> None:
    code = await _create_billing_code(db_session)
    order_id = uuid.uuid4()
    assignment = await billing_service.assign_code(order_id=order_id, billing_code_id=code.id)
    await billing_service.remove_assignment(assignment.id)
    items = await billing_service.get_order_billing(order_id)
    assert len(items) == 0


async def test_remove_nonexistent_assignment(billing_service: BillingService) -> None:
    with pytest.raises(BillingAssignmentNotFoundError):
        await billing_service.remove_assignment(uuid.uuid4())


async def test_revenue_summary_group_by_code_system(
    billing_service: BillingService, db_session: AsyncSession
) -> None:
    code = await _create_billing_code(db_session, code_system="CPT")
    order_id = uuid.uuid4()
    await billing_service.assign_code(order_id=order_id, billing_code_id=code.id)
    result = await billing_service.get_revenue_summary(group_by="code_system")
    assert len(result) >= 1
    assert result[0]["code_system"] == "CPT"


async def test_revenue_summary_group_by_modality(
    billing_service: BillingService, db_session: AsyncSession
) -> None:
    code = await _create_billing_code(db_session, code_system="CPT")
    # BillingCode.modality is None by default, so the group key should reflect that
    order_id = uuid.uuid4()
    await billing_service.assign_code(order_id=order_id, billing_code_id=code.id)
    result = await billing_service.get_revenue_summary(group_by="modality")
    assert len(result) >= 1
    assert "modality" in result[0]


async def test_revenue_summary_group_by_month(
    billing_service: BillingService, db_session: AsyncSession
) -> None:
    """GAP-M7: get_revenue_summary(group_by='month') groups assignments by YYYY-MM."""
    code = await _create_billing_code(db_session, code="99213", code_system="CPT")
    order_id = uuid.uuid4()
    await billing_service.assign_code(order_id=order_id, billing_code_id=code.id)

    result = await billing_service.get_revenue_summary(group_by="month")

    assert len(result) >= 1
    # Each row must have a "month" key formatted as YYYY-MM
    for row in result:
        assert "month" in row
        month_val = row["month"]
        assert month_val is not None
        # strftime(%Y-%m) format: exactly 7 characters
        assert len(str(month_val)) == 7, f"Unexpected month format: {month_val!r}"
    assert result[0]["assignment_count"] >= 1
