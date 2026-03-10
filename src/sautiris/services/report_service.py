"""Report lifecycle management service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import CriticalFinding, DomainEvent, EventBus, ReportFinalized
from sautiris.models.report import (
    RadiologyReport,
    ReportStatus,
    ReportTemplate,
    ReportVersion,
)
from sautiris.repositories.report import ReportRepository, ReportTemplateRepository

logger = structlog.get_logger(__name__)

_REPORT_UPDATABLE_FIELDS = frozenset(
    {
        "findings",
        "impression",
        "recommendation",
        "technique",
        "comparison",
        "clinical_information",
        "body",
        "is_critical",
        "reported_by",
        "reported_by_name",
        "modality",
        "body_part",
        "accession_number",
        "template_id",
    }
)

VALID_REPORT_TRANSITIONS: dict[ReportStatus, set[ReportStatus]] = {
    ReportStatus.DRAFT: {ReportStatus.PRELIMINARY, ReportStatus.CANCELLED},
    ReportStatus.PRELIMINARY: {ReportStatus.FINAL, ReportStatus.CANCELLED},
    ReportStatus.FINAL: {ReportStatus.AMENDED},
    ReportStatus.AMENDED: {ReportStatus.AMENDED},
    ReportStatus.CANCELLED: set(),
}


class ReportNotFoundError(Exception):
    pass


class InvalidReportTransitionError(Exception):
    pass


class ReportService:
    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None) -> None:
        self.session = session
        self.report_repo = ReportRepository(session)
        self.template_repo = ReportTemplateRepository(session)
        self._event_bus = event_bus

    async def _publish(self, event: DomainEvent) -> None:
        """Publish a domain event if an event bus is configured."""
        if self._event_bus is not None:
            errors = await self._event_bus.publish(event)
            if errors:
                for exc in errors:
                    logger.error(
                        "event_bus.handler_error",
                        event_type=event.event_type,
                        error=str(exc),
                    )
                if isinstance(event, CriticalFinding):
                    logger.critical(
                        "event_bus.critical_finding_handlers_failed",
                        event_type=event.event_type,
                        error_count=len(errors),
                        msg=(
                            "CriticalFinding handlers failed — patient safety event "
                            "may not have been delivered"
                        ),
                    )

    async def create_report(
        self,
        *,
        order_id: uuid.UUID,
        accession_number: str,
        reported_by: uuid.UUID,
        reported_by_name: str,
        modality: str | None = None,
        body_part: str | None = None,
        findings: str | None = None,
        impression: str | None = None,
        recommendation: str | None = None,
        technique: str | None = None,
        comparison: str | None = None,
        clinical_information: str | None = None,
        body: dict[str, object] | None = None,
        is_critical: bool = False,
    ) -> RadiologyReport:
        template = await self.template_repo.find_default_template(
            modality=modality, body_part=body_part
        )

        report = RadiologyReport(
            order_id=order_id,
            accession_number=accession_number,
            template_id=template.id if template else None,
            report_status=ReportStatus.DRAFT,
            findings=findings,
            impression=impression,
            recommendation=recommendation,
            technique=technique,
            comparison=comparison,
            clinical_information=clinical_information,
            body=body,
            is_critical=is_critical,
            reported_by=reported_by,
            reported_by_name=reported_by_name,
            reported_at=datetime.now(UTC),
        )
        created = await self.report_repo.create(report)

        await self._create_version(created, changed_by=reported_by)
        await self._emit("report.created", created)
        logger.info("report_created", report_id=str(created.id))
        return created

    async def get_report(self, report_id: uuid.UUID) -> RadiologyReport:
        report = await self.report_repo.get_by_id(report_id)
        if report is None:
            raise ReportNotFoundError(f"Report {report_id} not found")
        return report

    async def list_reports(
        self,
        *,
        order_id: uuid.UUID | None = None,
        status: ReportStatus | None = None,
        reported_by: uuid.UUID | None = None,
        is_critical: bool | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[RadiologyReport], int]:
        offset = (page - 1) * page_size
        items, total = await self.report_repo.list_with_filters(
            order_id=order_id,
            status=status,
            reported_by=reported_by,
            is_critical=is_critical,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=page_size,
        )
        return list(items), total

    async def update_report(
        self,
        report_id: uuid.UUID,
        *,
        changed_by: uuid.UUID,
        **updates: object,
    ) -> RadiologyReport:
        report = await self.get_report(report_id)
        current = report.report_status
        if current not in (ReportStatus.DRAFT, ReportStatus.PRELIMINARY):
            raise InvalidReportTransitionError(
                f"Cannot update report in {current} status; use amend instead"
            )
        known_fields = {c.key for c in inspect(RadiologyReport).mapper.column_attrs}
        unknown = set(updates.keys()) - known_fields
        if unknown:
            logger.warning("update.unknown_fields", fields=unknown, model="RadiologyReport")
        for key, value in updates.items():
            if key in _REPORT_UPDATABLE_FIELDS:
                setattr(report, key, value)
            elif key in known_fields:
                logger.warning("update.non_updatable_field", field=key, model="RadiologyReport")
        updated = await self.report_repo.update(report)
        await self._create_version(updated, changed_by=changed_by)
        return updated

    async def finalize_report(
        self,
        report_id: uuid.UUID,
        *,
        approved_by: uuid.UUID,
        approved_by_name: str,
    ) -> RadiologyReport:
        report = await self.get_report(report_id)
        current = report.report_status
        if ReportStatus.FINAL not in VALID_REPORT_TRANSITIONS.get(current, set()):
            raise InvalidReportTransitionError(f"Cannot finalize report from {current}")
        report.report_status = ReportStatus.FINAL
        report.approved_by = approved_by
        report.approved_by_name = approved_by_name
        report.approved_at = datetime.now(UTC)
        updated = await self.report_repo.update(report)
        await self._create_version(updated, changed_by=approved_by)
        await self._emit("report.finalized", updated)
        logger.info("report_finalized", report_id=str(report_id))
        return updated

    async def amend_report(
        self,
        report_id: uuid.UUID,
        *,
        changed_by: uuid.UUID,
        findings: str | None = None,
        impression: str | None = None,
        recommendation: str | None = None,
    ) -> RadiologyReport:
        report = await self.get_report(report_id)
        current = report.report_status
        if ReportStatus.AMENDED not in VALID_REPORT_TRANSITIONS.get(current, set()):
            raise InvalidReportTransitionError(f"Cannot amend report from {current}")
        report.report_status = ReportStatus.AMENDED
        if findings is not None:
            report.findings = findings
        if impression is not None:
            report.impression = impression
        if recommendation is not None:
            report.recommendation = recommendation
        updated = await self.report_repo.update(report)
        await self._create_version(updated, changed_by=changed_by)
        await self._emit("report.amended", updated)
        logger.info("report_amended", report_id=str(report_id))
        return updated

    async def create_addendum(
        self,
        parent_report_id: uuid.UUID,
        *,
        order_id: uuid.UUID,
        accession_number: str,
        reported_by: uuid.UUID,
        reported_by_name: str,
        findings: str | None = None,
        impression: str | None = None,
    ) -> RadiologyReport:
        parent = await self.get_report(parent_report_id)
        addendum = RadiologyReport(
            order_id=order_id,
            accession_number=accession_number,
            report_status=ReportStatus.DRAFT,
            is_addendum=True,
            parent_report_id=parent.id,
            reported_by=reported_by,
            reported_by_name=reported_by_name,
            reported_at=datetime.now(UTC),
            findings=findings,
            impression=impression,
        )
        created = await self.report_repo.create(addendum)
        await self._create_version(created, changed_by=reported_by)
        logger.info(
            "addendum_created",
            report_id=str(created.id),
            parent_id=str(parent.id),
        )
        return created

    async def get_versions(self, report_id: uuid.UUID) -> Sequence[ReportVersion]:
        return await self.report_repo.get_versions(report_id)

    async def _create_version(
        self,
        report: RadiologyReport,
        *,
        changed_by: uuid.UUID,
    ) -> ReportVersion:
        version_num = await self.report_repo.get_next_version_number(report.id)
        version = ReportVersion(
            tenant_id=report.tenant_id,
            report_id=report.id,
            version_number=version_num,
            status_at_version=report.report_status,
            findings=report.findings,
            impression=report.impression,
            body=report.body,
            changed_by=changed_by,
            changed_at=datetime.now(UTC),
        )
        return await self.report_repo.create_version(version)

    async def _emit(self, event_type: str, report: RadiologyReport) -> None:
        if event_type == "report.finalized":
            await self._publish(
                ReportFinalized(
                    order_id=str(report.order_id),
                    report_id=str(report.id),
                    accession_number=report.accession_number,
                    reported_by=str(report.reported_by) if report.reported_by else "",
                    is_critical=report.is_critical,
                    tenant_id=report.tenant_id,
                )
            )
            if report.is_critical:
                await self._publish(
                    CriticalFinding(
                        order_id=str(report.order_id),
                        report_id=str(report.id),
                        finding_description="Critical finding on finalized report",
                        tenant_id=report.tenant_id,
                    )
                )
        else:
            await self._publish(
                DomainEvent(
                    event_type=event_type,
                    payload={
                        "report_id": str(report.id),
                        "order_id": str(report.order_id),
                        "status": report.report_status,
                    },
                    tenant_id=report.tenant_id,
                )
            )

    # --- Template management ---

    async def list_templates(
        self,
        *,
        modality: str | None = None,
        is_active: bool | None = None,
    ) -> list[ReportTemplate]:
        items = await self.template_repo.list_templates(modality=modality, is_active=is_active)
        return list(items)

    async def create_template(
        self,
        *,
        name: str,
        modality: str | None = None,
        body_part: str | None = None,
        sections: dict[str, object] | None = None,
        is_default: bool = False,
        created_by: uuid.UUID | None = None,
    ) -> ReportTemplate:
        template = ReportTemplate(
            name=name,
            modality=modality,
            body_part=body_part,
            sections=sections,
            is_default=is_default,
            created_by=created_by,
        )
        return await self.template_repo.create(template)
