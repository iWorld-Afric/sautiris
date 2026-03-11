"""Tests for ReportService."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.order import RadiologyOrder
from sautiris.models.report import ReportStatus
from sautiris.services.report_service import (
    InvalidReportTransitionError,
    ReportNotFoundError,
    ReportService,
)
from tests.conftest import TEST_TENANT_ID, TEST_USER_ID


async def _make_order(session: AsyncSession) -> RadiologyOrder:
    order = RadiologyOrder(
        id=uuid.uuid4(),
        tenant_id=TEST_TENANT_ID,
        patient_id=uuid.uuid4(),
        accession_number=f"ACC-{uuid.uuid4().hex[:8]}",
        modality="CT",
        status="COMPLETED",
    )
    session.add(order)
    await session.flush()
    return order


@pytest.fixture
def report_service(db_session: AsyncSession) -> ReportService:
    return ReportService(db_session)


async def test_create_report(report_service: ReportService, db_session: AsyncSession) -> None:
    order = await _make_order(db_session)
    report = await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
        findings="Normal",
        impression="No abnormality",
    )
    assert report.id is not None
    assert report.report_status == ReportStatus.DRAFT
    assert report.findings == "Normal"


async def test_report_version_created_on_save(
    report_service: ReportService, db_session: AsyncSession
) -> None:
    order = await _make_order(db_session)
    report = await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
    )
    versions = await report_service.get_versions(report.id)
    assert len(versions) == 1
    assert versions[0].version_number == 1
    assert versions[0].status_at_version == ReportStatus.DRAFT


async def test_update_report_draft(report_service: ReportService, db_session: AsyncSession) -> None:
    order = await _make_order(db_session)
    report = await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
    )
    updated = await report_service.update_report(
        report.id, changed_by=TEST_USER_ID, findings="Updated findings"
    )
    assert updated.findings == "Updated findings"
    versions = await report_service.get_versions(report.id)
    assert len(versions) == 2


async def test_finalize_report(report_service: ReportService, db_session: AsyncSession) -> None:
    order = await _make_order(db_session)
    report = await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
    )
    # Move to PRELIMINARY first
    await report_service.update_report(
        report.id,
        changed_by=TEST_USER_ID,
    )
    report_obj = await report_service.get_report(report.id)
    report_obj.report_status = ReportStatus.PRELIMINARY
    await report_service.report_repo.update(report_obj)

    finalized = await report_service.finalize_report(
        report.id,
        approved_by=TEST_USER_ID,
        approved_by_name="Dr. Approver",
    )
    assert finalized.report_status == ReportStatus.FINAL
    assert finalized.approved_by == TEST_USER_ID
    assert finalized.approved_at is not None


async def test_cannot_update_final_report(
    report_service: ReportService, db_session: AsyncSession
) -> None:
    order = await _make_order(db_session)
    report = await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
    )
    report_obj = await report_service.get_report(report.id)
    report_obj.report_status = ReportStatus.PRELIMINARY
    await report_service.report_repo.update(report_obj)

    await report_service.finalize_report(
        report.id,
        approved_by=TEST_USER_ID,
        approved_by_name="Dr. Approver",
    )
    with pytest.raises(InvalidReportTransitionError):
        await report_service.update_report(report.id, changed_by=TEST_USER_ID, findings="Nope")


async def test_amend_final_report(report_service: ReportService, db_session: AsyncSession) -> None:
    order = await _make_order(db_session)
    report = await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
    )
    report_obj = await report_service.get_report(report.id)
    report_obj.report_status = ReportStatus.PRELIMINARY
    await report_service.report_repo.update(report_obj)

    await report_service.finalize_report(
        report.id,
        approved_by=TEST_USER_ID,
        approved_by_name="Dr. Approver",
    )
    amended = await report_service.amend_report(
        report.id,
        changed_by=TEST_USER_ID,
        findings="Amended findings",
    )
    assert amended.report_status == ReportStatus.AMENDED
    assert amended.findings == "Amended findings"


async def test_create_addendum(report_service: ReportService, db_session: AsyncSession) -> None:
    order = await _make_order(db_session)
    parent = await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
    )
    addendum = await report_service.create_addendum(
        parent.id,
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
        findings="Addendum findings",
    )
    assert addendum.is_addendum is True
    assert addendum.parent_report_id == parent.id
    assert addendum.findings == "Addendum findings"


async def test_get_report_not_found(report_service: ReportService) -> None:
    with pytest.raises(ReportNotFoundError):
        await report_service.get_report(uuid.uuid4())


async def test_create_template(report_service: ReportService) -> None:
    template = await report_service.create_template(
        name="CT Chest Template",
        modality="CT",
        body_part="CHEST",
        is_default=True,
    )
    assert template.id is not None
    assert template.name == "CT Chest Template"
    assert template.is_default is True


async def test_list_templates(report_service: ReportService) -> None:
    await report_service.create_template(name="T1", modality="CT")
    await report_service.create_template(name="T2", modality="MR")
    templates = await report_service.list_templates()
    assert len(templates) == 2


async def test_report_version_has_tenant_id(
    report_service: ReportService, db_session: AsyncSession
) -> None:
    """#27 — ReportVersion must have tenant_id matching parent report's tenant."""
    from sqlalchemy import select

    from sautiris.models.report import ReportVersion
    from tests.conftest import TEST_TENANT_ID

    order = await _make_order(db_session)
    await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
        findings="Normal chest",
    )

    result = await db_session.execute(select(ReportVersion))
    versions = result.scalars().all()
    assert len(versions) >= 1
    for v in versions:
        assert v.tenant_id == TEST_TENANT_ID


async def test_report_version_tenant_isolation(
    report_service: ReportService, db_session: AsyncSession
) -> None:
    """#27 — ReportVersions from tenant A must not appear in tenant B queries."""

    from sqlalchemy import select

    from sautiris.core.tenancy import set_current_tenant_id
    from sautiris.models.report import ReportVersion
    from tests.conftest import TEST_TENANT_B_ID, TEST_TENANT_ID

    # Create report under tenant A
    set_current_tenant_id(TEST_TENANT_ID)
    order = await _make_order(db_session)
    await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
    )

    # Switch to tenant B — must see 0 ReportVersions for that tenant
    set_current_tenant_id(TEST_TENANT_B_ID)
    result = await db_session.execute(
        select(ReportVersion).where(ReportVersion.tenant_id == TEST_TENANT_B_ID)
    )
    tenant_b_versions = result.scalars().all()
    assert len(tenant_b_versions) == 0


# ---------------------------------------------------------------------------
# GAP-6: CriticalFinding event emission tests
# ---------------------------------------------------------------------------


async def test_finalize_critical_report_emits_critical_finding_event(
    db_session: AsyncSession,
) -> None:
    """Finalizing a report with is_critical=True must emit CriticalFinding event."""

    from sautiris.core.events import CriticalFinding, EventBus

    # Set up event bus with a handler that captures events
    bus = EventBus()
    captured: list[CriticalFinding] = []

    async def _capture(event: object) -> None:
        if isinstance(event, CriticalFinding):
            captured.append(event)

    bus.subscribe("finding.critical", _capture)

    service = ReportService(db_session, event_bus=bus)
    order = await _make_order(db_session)
    report = await service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Critical",
        is_critical=True,  # critical report
    )
    # Advance to PRELIMINARY so we can finalize
    report_obj = await service.get_report(report.id)
    report_obj.report_status = ReportStatus.PRELIMINARY
    await service.report_repo.update(report_obj)

    await service.finalize_report(
        report.id,
        approved_by=TEST_USER_ID,
        approved_by_name="Dr. Approver",
    )

    assert len(captured) == 1
    assert captured[0].report_id == str(report.id)


async def test_finalize_non_critical_report_does_not_emit_critical_finding(
    db_session: AsyncSession,
) -> None:
    """Finalizing a non-critical report must NOT emit CriticalFinding event."""
    from sautiris.core.events import CriticalFinding, EventBus

    bus = EventBus()
    captured: list[CriticalFinding] = []

    async def _capture(event: object) -> None:
        if isinstance(event, CriticalFinding):
            captured.append(event)

    bus.subscribe("finding.critical", _capture)

    service = ReportService(db_session, event_bus=bus)
    order = await _make_order(db_session)
    report = await service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Normal",
        is_critical=False,  # NOT critical
    )
    report_obj = await service.get_report(report.id)
    report_obj.report_status = ReportStatus.PRELIMINARY
    await service.report_repo.update(report_obj)

    await service.finalize_report(
        report.id,
        approved_by=TEST_USER_ID,
        approved_by_name="Dr. Approver",
    )

    assert len(captured) == 0  # no CriticalFinding emitted


async def test_event_publish_errors_are_logged(
    db_session: AsyncSession,
) -> None:
    """_publish logs errors when non-critical handlers raise exceptions."""
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    # Register a handler that always fails
    async def _failing_handler(event: object) -> None:
        raise ValueError("handler error")

    bus.subscribe("report.finalized", _failing_handler)

    service = ReportService(db_session, event_bus=bus)
    order = await _make_order(db_session)
    report = await service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
    )
    report_obj = await service.get_report(report.id)
    report_obj.report_status = ReportStatus.PRELIMINARY
    await service.report_repo.update(report_obj)

    # finalize_report → _publish (in mixin) → handler fails → mixin logger.error
    with patch("sautiris.services.mixins.logger") as mock_logger:
        await service.finalize_report(
            report.id,
            approved_by=TEST_USER_ID,
            approved_by_name="Dr. Approver",
        )
        # logger.error was called with handler failure info
        mock_logger.error.assert_called()


# ---------------------------------------------------------------------------
# GAP-I6: CriticalFinding handler failure is logged at CRITICAL level
# ---------------------------------------------------------------------------


async def test_critical_finding_handler_failure_logged_at_critical_level(
    db_session: AsyncSession,
) -> None:
    """GAP-I6: When a CriticalFinding event handler fails, _publish logs at CRITICAL level.

    The ReportService._publish method must call logger.critical when any
    CriticalFinding event handler raises — because an undelivered critical
    finding is a patient-safety event.
    """
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    # Register a handler for CriticalFinding that always fails
    async def _failing_critical_handler(event: object) -> None:
        raise RuntimeError("paging system offline")

    bus.subscribe("finding.critical", _failing_critical_handler)

    service = ReportService(db_session, event_bus=bus)
    order = await _make_order(db_session)
    report = await service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Critical",
        is_critical=True,
    )
    report_obj = await service.get_report(report.id)
    report_obj.report_status = ReportStatus.PRELIMINARY
    await service.report_repo.update(report_obj)

    # _publish is in the mixin; patch mixins.logger for critical event logging
    with patch("sautiris.services.mixins.logger") as mock_logger:
        await service.finalize_report(
            report.id,
            approved_by=TEST_USER_ID,
            approved_by_name="Dr. Approver",
        )
        # logger.critical must be called when CriticalFinding handler fails
        mock_logger.critical.assert_called()
        # The critical call must mention the critical event handler failure
        call_args = mock_logger.critical.call_args
        event_name = call_args[0][0] if call_args[0] else str(call_args)
        assert "critical_event_handlers_failed" in event_name


# ---------------------------------------------------------------------------
# GAP-H5: ReportService.update_report() — unknown field warning
# ---------------------------------------------------------------------------


async def test_update_report_unknown_field_logs_warning(
    report_service: ReportService, db_session: AsyncSession
) -> None:
    """GAP-H5: Passing an unknown field to update_report() logs a warning and does not crash."""
    from unittest.mock import patch

    order = await _make_order(db_session)
    report = await report_service.create_report(
        order_id=order.id,
        accession_number=order.accession_number,
        reported_by=TEST_USER_ID,
        reported_by_name="Dr. Test",
    )

    with patch("sautiris.services.report_service.logger") as mock_logger:
        updated = await report_service.update_report(
            report.id,
            changed_by=TEST_USER_ID,
            bogus_field="should_be_ignored",
        )

    assert updated is not None  # no crash
    mock_logger.warning.assert_called()
    warning_key = mock_logger.warning.call_args[0][0]
    assert "unknown_fields" in warning_key
