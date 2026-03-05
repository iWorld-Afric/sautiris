"""Tests for OrderService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.order import OrderStatus
from sautiris.services.order_service import (
    InvalidTransitionError,
    OrderNotFoundError,
    OrderService,
)
from tests.conftest import TEST_TENANT_ID


@pytest.fixture
def order_service(db_session: AsyncSession) -> OrderService:
    return OrderService(db_session)


async def test_create_order(order_service: OrderService) -> None:
    order = await order_service.create_order(
        patient_id=uuid.uuid4(),
        modality="CT",
        urgency="ROUTINE",
        clinical_indication="Chest pain",
    )
    assert order.id is not None
    assert order.status == OrderStatus.REQUESTED
    assert order.modality == "CT"
    assert order.accession_number.endswith("-CT-00001")
    assert order.tenant_id == TEST_TENANT_ID


async def test_create_order_accession_sequential(
    order_service: OrderService,
) -> None:
    o1 = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    o2 = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    assert o1.accession_number != o2.accession_number
    assert o1.accession_number.endswith("00001")
    assert o2.accession_number.endswith("00002")


async def test_get_order(order_service: OrderService) -> None:
    created = await order_service.create_order(patient_id=uuid.uuid4(), modality="MR")
    fetched = await order_service.get_order(created.id)
    assert fetched.id == created.id
    assert fetched.modality == "MR"


async def test_get_order_not_found(order_service: OrderService) -> None:
    with pytest.raises(OrderNotFoundError):
        await order_service.get_order(uuid.uuid4())


async def test_list_orders(order_service: OrderService) -> None:
    await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.create_order(patient_id=uuid.uuid4(), modality="MR")

    items, total = await order_service.list_orders()
    assert total == 2
    assert len(items) == 2


async def test_list_orders_filter_modality(order_service: OrderService) -> None:
    await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.create_order(patient_id=uuid.uuid4(), modality="MR")

    items, total = await order_service.list_orders(modality="CT")
    assert total == 1
    assert items[0].modality == "CT"


async def test_update_order_requested(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    updated = await order_service.update_order(order.id, clinical_indication="Updated")
    assert updated.clinical_indication == "Updated"


async def test_update_order_completed_fails(
    order_service: OrderService,
) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.schedule_order(order.id, datetime.now(UTC))
    await order_service.start_exam(order.id)
    await order_service.complete_exam(order.id)

    with pytest.raises(InvalidTransitionError):
        await order_service.update_order(order.id, clinical_indication="Nope")


async def test_schedule_order(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    scheduled = await order_service.schedule_order(order.id, datetime.now(UTC))
    assert scheduled.status == OrderStatus.SCHEDULED
    assert scheduled.scheduled_at is not None


async def test_start_exam(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.schedule_order(order.id, datetime.now(UTC))
    started = await order_service.start_exam(order.id)
    assert started.status == OrderStatus.IN_PROGRESS
    assert started.started_at is not None


async def test_complete_exam(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.schedule_order(order.id, datetime.now(UTC))
    await order_service.start_exam(order.id)
    completed = await order_service.complete_exam(order.id)
    assert completed.status == OrderStatus.COMPLETED
    assert completed.completed_at is not None


async def test_cancel_order(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    cancelled = await order_service.cancel_order(order.id, reason="Patient refused")
    assert cancelled.status == OrderStatus.CANCELLED
    assert "Patient refused" in (cancelled.special_instructions or "")


async def test_cancel_completed_order(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.schedule_order(order.id, datetime.now(UTC))
    await order_service.start_exam(order.id)
    await order_service.complete_exam(order.id)
    cancelled = await order_service.cancel_order(order.id, reason="Clinically inappropriate")
    assert cancelled.status == OrderStatus.CANCELLED
    assert "Clinically inappropriate" in (cancelled.special_instructions or "")


async def test_invalid_transition_requested_to_completed(
    order_service: OrderService,
) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    with pytest.raises(InvalidTransitionError):
        await order_service.complete_exam(order.id)


async def test_invalid_transition_cancelled_to_scheduled(
    order_service: OrderService,
) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.cancel_order(order.id, reason="Test cancellation")
    with pytest.raises(InvalidTransitionError):
        await order_service.schedule_order(order.id, datetime.now(UTC))


async def test_get_order_stats(order_service: OrderService) -> None:
    await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.create_order(patient_id=uuid.uuid4(), modality="MR")
    stats = await order_service.get_order_stats()
    assert stats.get("REQUESTED", 0) == 2


async def test_get_next_accession(order_service: OrderService) -> None:
    accession = await order_service.get_next_accession("CT")
    assert "CT" in accession
    assert accession.endswith("00001")
