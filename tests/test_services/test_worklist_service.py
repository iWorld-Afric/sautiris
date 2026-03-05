"""Tests for WorklistService."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.worklist import MPPSStatus, WorklistStatus
from sautiris.services.worklist_service import (
    InvalidWorklistTransitionError,
    WorklistItemNotFoundError,
    WorklistService,
)


@pytest.fixture
def worklist_service(db_session: AsyncSession) -> WorklistService:
    return WorklistService(db_session)


async def test_create_worklist_item(worklist_service: WorklistService) -> None:
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-001",
        patient_id="PAT001",
        patient_name="DOE^JOHN",
        modality="CT",
    )
    assert item.id is not None
    assert item.status == WorklistStatus.SCHEDULED


async def test_get_item(worklist_service: WorklistService) -> None:
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-002",
        patient_id="PAT002",
        patient_name="DOE^JANE",
        modality="MR",
    )
    fetched = await worklist_service.get_item(item.id)
    assert fetched.patient_name == "DOE^JANE"


async def test_get_item_not_found(worklist_service: WorklistService) -> None:
    with pytest.raises(WorklistItemNotFoundError):
        await worklist_service.get_item(uuid.uuid4())


async def test_update_step_status(worklist_service: WorklistService) -> None:
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-003",
        patient_id="PAT003",
        patient_name="DOE^BOB",
        modality="CT",
    )
    updated = await worklist_service.update_procedure_step_status(
        item.id, WorklistStatus.IN_PROGRESS
    )
    assert updated.status == WorklistStatus.IN_PROGRESS


async def test_invalid_worklist_transition(worklist_service: WorklistService) -> None:
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-004",
        patient_id="PAT004",
        patient_name="DOE^SUE",
        modality="CT",
    )
    await worklist_service.update_procedure_step_status(item.id, WorklistStatus.IN_PROGRESS)
    await worklist_service.update_procedure_step_status(item.id, WorklistStatus.COMPLETED)
    with pytest.raises(InvalidWorklistTransitionError):
        await worklist_service.update_procedure_step_status(item.id, WorklistStatus.IN_PROGRESS)


async def test_receive_mpps_completed(worklist_service: WorklistService) -> None:
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-005",
        patient_id="PAT005",
        patient_name="DOE^TIM",
        modality="CT",
    )
    await worklist_service.update_procedure_step_status(item.id, WorklistStatus.IN_PROGRESS)
    updated = await worklist_service.receive_mpps(
        item.id, mpps_status=MPPSStatus.COMPLETED, mpps_uid="1.2.3.4"
    )
    assert updated.mpps_status == MPPSStatus.COMPLETED
    assert updated.mpps_uid == "1.2.3.4"
    assert updated.status == WorklistStatus.COMPLETED


async def test_get_stats(worklist_service: WorklistService) -> None:
    await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-006",
        patient_id="PAT006",
        patient_name="DOE^A",
        modality="CT",
    )
    stats = await worklist_service.get_stats()
    assert stats.get("SCHEDULED", 0) == 1
