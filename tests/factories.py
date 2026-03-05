"""Factory Boy factories for all SautiRIS models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import factory

from sautiris.models.alert import CriticalAlert
from sautiris.models.analytics import TATMetric
from sautiris.models.billing import BillingCode, OrderBilling
from sautiris.models.dose import DoseRecord
from sautiris.models.order import RadiologyOrder
from sautiris.models.pacs import PACSConnection
from sautiris.models.peer_review import Discrepancy, PeerReview
from sautiris.models.report import RadiologyReport, ReportTemplate, ReportVersion
from sautiris.models.schedule import ScheduleSlot
from sautiris.models.worklist import WorklistItem

TEST_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class RadiologyOrderFactory(factory.Factory):
    class Meta:
        model = RadiologyOrder

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    patient_id = factory.LazyFunction(uuid.uuid4)
    accession_number = factory.LazyFunction(lambda: f"ACC-{uuid.uuid4().hex[:8]}")
    modality = "CT"
    status = "REQUESTED"
    urgency = "ROUTINE"


class ScheduleSlotFactory(factory.Factory):
    class Meta:
        model = ScheduleSlot

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    order_id = factory.LazyFunction(uuid.uuid4)
    room_id = "ROOM-CT-1"
    modality = "CT"
    scheduled_start = factory.LazyFunction(lambda: datetime.now(UTC))
    scheduled_end = factory.LazyFunction(lambda: datetime.now(UTC))
    duration_minutes = 30
    status = "AVAILABLE"


class ReportTemplateFactory(factory.Factory):
    class Meta:
        model = ReportTemplate

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    name = "Default CT Template"
    modality = "CT"
    is_default = True
    is_active = True


class RadiologyReportFactory(factory.Factory):
    class Meta:
        model = RadiologyReport

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    order_id = factory.LazyFunction(uuid.uuid4)
    accession_number = factory.LazyFunction(lambda: f"ACC-{uuid.uuid4().hex[:8]}")
    report_status = "DRAFT"
    findings = "No acute findings."
    impression = "Normal examination."


class ReportVersionFactory(factory.Factory):
    class Meta:
        model = ReportVersion

    id = factory.LazyFunction(uuid.uuid4)
    report_id = factory.LazyFunction(uuid.uuid4)
    version_number = 1
    status_at_version = "DRAFT"
    changed_at = factory.LazyFunction(lambda: datetime.now(UTC))


class WorklistItemFactory(factory.Factory):
    class Meta:
        model = WorklistItem

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    order_id = factory.LazyFunction(uuid.uuid4)
    accession_number = factory.LazyFunction(lambda: f"ACC-{uuid.uuid4().hex[:8]}")
    patient_id = "PAT001"
    patient_name = "DOE^JOHN"
    modality = "CT"
    status = "SCHEDULED"


class BillingCodeFactory(factory.Factory):
    class Meta:
        model = BillingCode

    id = factory.LazyFunction(uuid.uuid4)
    code_system = "CPT"
    code = "71046"
    display = "Chest X-ray, 2 views"
    is_active = True


class OrderBillingFactory(factory.Factory):
    class Meta:
        model = OrderBilling

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    order_id = factory.LazyFunction(uuid.uuid4)
    billing_code_id = factory.LazyFunction(uuid.uuid4)
    quantity = 1


class DoseRecordFactory(factory.Factory):
    class Meta:
        model = DoseRecord

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    order_id = factory.LazyFunction(uuid.uuid4)
    modality = "CT"
    source = "MANUAL"


class PeerReviewFactory(factory.Factory):
    class Meta:
        model = PeerReview

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    report_id = factory.LazyFunction(uuid.uuid4)
    order_id = factory.LazyFunction(uuid.uuid4)
    reviewer_id = factory.LazyFunction(uuid.uuid4)
    review_type = "RANDOM"


class DiscrepancyFactory(factory.Factory):
    class Meta:
        model = Discrepancy

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    peer_review_id = factory.LazyFunction(uuid.uuid4)
    severity = "MINOR"
    category = "PERCEPTUAL"


class CriticalAlertFactory(factory.Factory):
    class Meta:
        model = CriticalAlert

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    order_id = factory.LazyFunction(uuid.uuid4)
    alert_type = "CRITICAL_FINDING"
    urgency = "IMMEDIATE"


class TATMetricFactory(factory.Factory):
    class Meta:
        model = TATMetric

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    order_id = factory.LazyFunction(uuid.uuid4)
    modality = "CT"


class PACSConnectionFactory(factory.Factory):
    class Meta:
        model = PACSConnection

    id = factory.LazyFunction(uuid.uuid4)
    tenant_id = TEST_TENANT_ID
    name = "Test Orthanc"
    pacs_type = "ORTHANC"
    base_url = "http://localhost:8042"
    is_default = True
    is_active = True
