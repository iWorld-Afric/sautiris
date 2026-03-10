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


async def test_create_item_generates_study_instance_uid(
    worklist_service: WorklistService,
) -> None:
    """Newly created WorklistItem has a valid DICOM study_instance_uid populated."""
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-UID-001",
        patient_id="PAT-UID-001",
        patient_name="DOE^UID",
        modality="CT",
    )
    assert item.study_instance_uid is not None
    assert len(item.study_instance_uid) > 0
    # Valid DICOM UID format contains dots
    assert "." in item.study_instance_uid


async def test_create_items_have_unique_study_instance_uids(
    worklist_service: WorklistService,
) -> None:
    """Each WorklistItem gets a distinct study_instance_uid."""
    item1 = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-UID-002",
        patient_id="PAT-UID-002",
        patient_name="DOE^UNIQUE1",
        modality="CT",
    )
    item2 = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-UID-003",
        patient_id="PAT-UID-003",
        patient_name="DOE^UNIQUE2",
        modality="MR",
    )
    assert item1.study_instance_uid != item2.study_instance_uid


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


# ---------------------------------------------------------------------------
# GAP: WorklistService._publish error logging
# ---------------------------------------------------------------------------


async def test_worklist_publish_handler_error_is_logged(db_session: AsyncSession) -> None:
    """WorklistService._publish logs ERROR for each failing event handler.

    WorklistService._publish uses logger.error (not warning) for handler
    failures. ExamCompleted failures additionally produce a second logger.error
    call flagging the workflow-critical nature of the failure.
    """
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    async def _failing_handler(event: object) -> None:
        raise ValueError("worklist notification down")

    # Subscribe to the exam.started event (triggered by IN_PROGRESS transition)
    bus.subscribe("exam.started", _failing_handler)
    svc = WorklistService(db_session, event_bus=bus)

    # Create a worklist item and transition to IN_PROGRESS
    item = await svc.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-PUBLISH-ERR",
        patient_id="PAT-ERR",
        patient_name="DOE^ERR",
        modality="CT",
    )

    with patch("sautiris.services.worklist_service.logger") as mock_logger:
        await svc.update_procedure_step_status(item.id, WorklistStatus.IN_PROGRESS)
        # logger.error must be called for the handler failure
        mock_logger.error.assert_called()


async def test_worklist_exam_completed_handler_failure_logs_critical(
    db_session: AsyncSession,
) -> None:
    """ExamCompleted handler failure triggers logger.critical for workflow impact.

    WorklistService._publish checks isinstance(event, ExamCompleted) and emits
    logger.critical with 'exam_completed_handlers_failed' to signal that
    a workflow-critical event was not delivered.
    """
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    async def _failing_handler(event: object) -> None:
        raise RuntimeError("order service unreachable")

    bus.subscribe("exam.completed", _failing_handler)
    svc = WorklistService(db_session, event_bus=bus)

    # Create item and advance to IN_PROGRESS (needed to allow COMPLETED transition)
    item = await svc.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-EXAM-COMP-ERR",
        patient_id="PAT-COMP",
        patient_name="SMITH^JOHN",
        modality="MR",
    )
    await svc.update_procedure_step_status(item.id, WorklistStatus.IN_PROGRESS)

    with patch("sautiris.services.worklist_service.logger") as mock_logger:
        await svc.update_procedure_step_status(item.id, WorklistStatus.COMPLETED)
        # logger.error called for each handler error
        mock_logger.error.assert_called()
        # logger.critical called for ExamCompleted workflow-critical escalation
        mock_logger.critical.assert_called()
        critical_key = mock_logger.critical.call_args[0][0]
        assert "exam_completed_handlers_failed" in critical_key


async def test_worklist_publish_no_error_does_not_log_error(
    db_session: AsyncSession,
) -> None:
    """_publish does NOT call logger.error when all handlers succeed."""
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    async def _ok_handler(event: object) -> None:
        pass  # success

    bus.subscribe("exam.started", _ok_handler)
    svc = WorklistService(db_session, event_bus=bus)

    item = await svc.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-NO-ERR",
        patient_id="PAT-NO-ERR",
        patient_name="DOE^JANE",
        modality="CT",
    )

    with patch("sautiris.services.worklist_service.logger") as mock_logger:
        await svc.update_procedure_step_status(item.id, WorklistStatus.IN_PROGRESS)
        handler_errors = [
            call
            for call in mock_logger.error.call_args_list
            if "event_bus.handler_error" in str(call.args)
        ]
        assert len(handler_errors) == 0


# ---------------------------------------------------------------------------
# GAP-R4-3: receive_mpps DISCONTINUED path
# ---------------------------------------------------------------------------


async def test_receive_mpps_discontinued_from_in_progress(
    worklist_service: WorklistService,
) -> None:
    """receive_mpps with DISCONTINUED transitions an IN_PROGRESS item to DISCONTINUED."""
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-DISC-01",
        patient_id="PAT-DISC-01",
        patient_name="DOE^DISC",
        modality="CT",
    )
    # Advance to IN_PROGRESS first
    await worklist_service.update_procedure_step_status(item.id, WorklistStatus.IN_PROGRESS)

    updated = await worklist_service.receive_mpps(
        item.id,
        mpps_status=MPPSStatus.DISCONTINUED,
        mpps_uid="1.2.840.10008.5.1.4.1.1.99",
    )

    assert updated.mpps_status == MPPSStatus.DISCONTINUED
    assert updated.status == WorklistStatus.DISCONTINUED


async def test_receive_mpps_discontinued_from_scheduled(
    worklist_service: WorklistService,
) -> None:
    """receive_mpps with DISCONTINUED on a SCHEDULED item also marks it DISCONTINUED."""
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-DISC-02",
        patient_id="PAT-DISC-02",
        patient_name="SMITH^DISC",
        modality="MR",
    )
    # item is still SCHEDULED — DISCONTINUED MPPS should still mark it DISCONTINUED
    updated = await worklist_service.receive_mpps(
        item.id,
        mpps_status=MPPSStatus.DISCONTINUED,
    )

    assert updated.mpps_status == MPPSStatus.DISCONTINUED
    assert updated.status == WorklistStatus.DISCONTINUED


async def test_receive_mpps_discontinued_sets_mpps_uid(
    worklist_service: WorklistService,
) -> None:
    """receive_mpps stores the mpps_uid when provided alongside DISCONTINUED status."""
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-DISC-03",
        patient_id="PAT-DISC-03",
        patient_name="JONES^DISC",
        modality="CR",
    )
    uid = "2.25.1234567890"
    updated = await worklist_service.receive_mpps(
        item.id,
        mpps_status=MPPSStatus.DISCONTINUED,
        mpps_uid=uid,
    )

    assert updated.mpps_uid == uid


# ---------------------------------------------------------------------------
# GAP-H6: receive_mpps() COMPLETED on non-IN_PROGRESS item
# ---------------------------------------------------------------------------


async def test_receive_mpps_completed_on_scheduled_updates_mpps_status_only(
    worklist_service: WorklistService,
) -> None:
    """GAP-H6: receive_mpps(COMPLETED) on a SCHEDULED item sets mpps_status=COMPLETED
    but leaves worklist status as SCHEDULED (transition only allowed from IN_PROGRESS)."""
    item = await worklist_service.create_worklist_item(
        order_id=uuid.uuid4(),
        accession_number="ACC-MPPS-SCHED",
        patient_id="PAT-MPPS-S",
        patient_name="GAP^H6",
        modality="CT",
    )
    assert item.status == WorklistStatus.SCHEDULED

    updated = await worklist_service.receive_mpps(
        item.id,
        mpps_status=MPPSStatus.COMPLETED,
        mpps_uid="1.2.3.4.5.6",
    )

    # mpps_status is updated…
    assert updated.mpps_status == MPPSStatus.COMPLETED
    # …but worklist status stays SCHEDULED because item was not IN_PROGRESS
    assert updated.status == WorklistStatus.SCHEDULED
