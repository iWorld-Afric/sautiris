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
