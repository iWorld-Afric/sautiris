"""Initial SautiRIS schema — 20 tables.

Revision ID: ris001
Revises:
Create Date: 2026-03-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ris001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- radiology_orders ---
    op.create_table(
        "radiology_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("encounter_id", sa.Uuid(), nullable=True),
        sa.Column("accession_number", sa.String(64), nullable=False, unique=True),
        sa.Column("order_number", sa.String(64), nullable=True),
        sa.Column("requesting_physician_id", sa.Uuid(), nullable=True),
        sa.Column("requesting_physician_name", sa.String(255), nullable=True),
        sa.Column("modality", sa.String(16), nullable=False),
        sa.Column("body_part", sa.String(128), nullable=True),
        sa.Column("laterality", sa.String(16), nullable=True),
        sa.Column("procedure_code", sa.String(32), nullable=True),
        sa.Column("procedure_description", sa.Text(), nullable=True),
        sa.Column("clinical_indication", sa.Text(), nullable=True),
        sa.Column("patient_history", sa.Text(), nullable=True),
        sa.Column("urgency", sa.String(16), nullable=False, server_default="ROUTINE"),
        sa.Column("status", sa.String(32), nullable=False, server_default="REQUESTED"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("study_instance_uid", sa.String(128), nullable=True),
        sa.Column("special_instructions", sa.Text(), nullable=True),
        sa.Column("transport_mode", sa.String(32), nullable=True),
        sa.Column("isolation_precautions", sa.String(64), nullable=True),
        sa.Column("pregnant", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_radiology_orders_tenant", "radiology_orders", ["tenant_id"])
    op.create_index("ix_radiology_orders_accession", "radiology_orders", ["accession_number"])
    op.create_index("ix_radiology_orders_patient", "radiology_orders", ["patient_id"])
    op.create_index("ix_radiology_orders_status", "radiology_orders", ["status"])
    op.create_index("ix_radiology_orders_scheduled", "radiology_orders", ["scheduled_at"])
    op.create_index("ix_radiology_orders_modality", "radiology_orders", ["modality"])

    # --- schedule_slots ---
    op.create_table(
        "schedule_slots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("radiology_orders.id"), nullable=False),
        sa.Column("room_id", sa.String(64), nullable=False),
        sa.Column("modality", sa.String(16), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("technologist_id", sa.Uuid(), nullable=True),
        sa.Column("technologist_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="AVAILABLE"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedule_slots_tenant", "schedule_slots", ["tenant_id"])
    op.create_index("ix_schedule_slots_order", "schedule_slots", ["order_id"])
    op.create_index("ix_schedule_slots_room", "schedule_slots", ["room_id"])

    # --- report_templates ---
    op.create_table(
        "report_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("modality", sa.String(16), nullable=True),
        sa.Column("body_part", sa.String(128), nullable=True),
        sa.Column("sections", postgresql.JSONB(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_templates_tenant", "report_templates", ["tenant_id"])

    # --- radiology_reports ---
    op.create_table(
        "radiology_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("radiology_orders.id"), nullable=False),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey("report_templates.id"), nullable=True),
        sa.Column("accession_number", sa.String(64), nullable=False),
        sa.Column("report_status", sa.String(32), nullable=False, server_default="DRAFT"),
        sa.Column("findings", sa.Text(), nullable=True),
        sa.Column("impression", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("technique", sa.Text(), nullable=True),
        sa.Column("comparison", sa.Text(), nullable=True),
        sa.Column("clinical_information", sa.Text(), nullable=True),
        sa.Column("body", postgresql.JSONB(), nullable=True),
        sa.Column("is_critical", sa.Boolean(), server_default="false"),
        sa.Column("is_addendum", sa.Boolean(), server_default="false"),
        sa.Column(
            "parent_report_id",
            sa.Uuid(),
            sa.ForeignKey("radiology_reports.id"),
            nullable=True,
        ),
        sa.Column("reported_by", sa.Uuid(), nullable=True),
        sa.Column("reported_by_name", sa.String(255), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by_name", sa.String(255), nullable=True),
        sa.Column("transcribed_by", sa.Uuid(), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("distributed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_radiology_reports_tenant", "radiology_reports", ["tenant_id"])
    op.create_index("ix_radiology_reports_order", "radiology_reports", ["order_id"])
    op.create_index("ix_radiology_reports_accession", "radiology_reports", ["accession_number"])
    op.create_index("ix_radiology_reports_status", "radiology_reports", ["report_status"])

    # --- report_versions ---
    op.create_table(
        "report_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("radiology_reports.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status_at_version", sa.String(32), nullable=False),
        sa.Column("findings", sa.Text(), nullable=True),
        sa.Column("impression", sa.Text(), nullable=True),
        sa.Column("body", postgresql.JSONB(), nullable=True),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_versions_report", "report_versions", ["report_id"])

    # --- worklist_items ---
    op.create_table(
        "worklist_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("radiology_orders.id"), nullable=False),
        sa.Column("schedule_slot_id", sa.Uuid(), sa.ForeignKey("schedule_slots.id"), nullable=True),
        sa.Column("accession_number", sa.String(64), nullable=False),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("patient_name", sa.String(255), nullable=False),
        sa.Column("patient_dob", sa.Date(), nullable=True),
        sa.Column("patient_sex", sa.String(1), nullable=True),
        sa.Column("modality", sa.String(16), nullable=False),
        sa.Column("scheduled_station_ae_title", sa.String(64), nullable=True),
        sa.Column("scheduled_procedure_step_id", sa.String(64), nullable=True),
        sa.Column("scheduled_procedure_step_description", sa.Text(), nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_procedure_id", sa.String(64), nullable=True),
        sa.Column("requested_procedure_description", sa.Text(), nullable=True),
        sa.Column("referring_physician_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="SCHEDULED"),
        sa.Column("mpps_status", sa.String(32), nullable=True),
        sa.Column("mpps_uid", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worklist_items_tenant", "worklist_items", ["tenant_id"])
    op.create_index("ix_worklist_items_accession", "worklist_items", ["accession_number"])
    op.create_index("ix_worklist_items_order", "worklist_items", ["order_id"])

    # --- billing_codes ---
    op.create_table(
        "billing_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code_system", sa.String(16), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("display", sa.String(512), nullable=False),
        sa.Column("modality", sa.String(16), nullable=True),
        sa.Column("body_part", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- order_billing ---
    op.create_table(
        "order_billing",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("radiology_orders.id"), nullable=False),
        sa.Column("billing_code_id", sa.Uuid(), sa.ForeignKey("billing_codes.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("assigned_by", sa.Uuid(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_billing_tenant", "order_billing", ["tenant_id"])
    op.create_index("ix_order_billing_order", "order_billing", ["order_id"])

    # --- dose_records ---
    op.create_table(
        "dose_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("radiology_orders.id"), nullable=False),
        sa.Column("study_instance_uid", sa.String(128), nullable=True),
        sa.Column("modality", sa.String(16), nullable=False),
        sa.Column("ctdi_vol", sa.Numeric(10, 4), nullable=True),
        sa.Column("dlp", sa.Numeric(10, 4), nullable=True),
        sa.Column("dap", sa.Numeric(10, 4), nullable=True),
        sa.Column("effective_dose", sa.Numeric(10, 4), nullable=True),
        sa.Column("entrance_dose", sa.Numeric(10, 4), nullable=True),
        sa.Column("num_exposures", sa.Integer(), nullable=True),
        sa.Column("kvp", sa.Numeric(7, 2), nullable=True),
        sa.Column("tube_current_ma", sa.Numeric(7, 2), nullable=True),
        sa.Column("exposure_time_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("protocol_name", sa.String(255), nullable=True),
        sa.Column("body_part", sa.String(128), nullable=True),
        sa.Column("exceeds_drl", sa.Boolean(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="MANUAL"),
        sa.Column("recorded_by", sa.Uuid(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dose_records_tenant", "dose_records", ["tenant_id"])
    op.create_index("ix_dose_records_order", "dose_records", ["order_id"])

    # --- peer_reviews ---
    op.create_table(
        "peer_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("radiology_reports.id"), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("radiology_orders.id"), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_name", sa.String(255), nullable=True),
        sa.Column("original_reporter_id", sa.Uuid(), nullable=True),
        sa.Column("review_type", sa.String(32), nullable=False, server_default="RANDOM"),
        sa.Column("agreement_score", sa.String(32), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_peer_reviews_tenant", "peer_reviews", ["tenant_id"])
    op.create_index("ix_peer_reviews_report", "peer_reviews", ["report_id"])
    op.create_index("ix_peer_reviews_order", "peer_reviews", ["order_id"])

    # --- discrepancies ---
    op.create_table(
        "discrepancies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("peer_review_id", sa.Uuid(), sa.ForeignKey("peer_reviews.id"), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("clinical_impact", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discrepancies_tenant", "discrepancies", ["tenant_id"])
    op.create_index("ix_discrepancies_peer_review", "discrepancies", ["peer_review_id"])

    # --- critical_alerts ---
    op.create_table(
        "critical_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("radiology_orders.id"), nullable=False),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("radiology_reports.id"), nullable=True),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("finding_description", sa.Text(), nullable=True),
        sa.Column("urgency", sa.String(16), nullable=False, server_default="URGENT"),
        sa.Column("notified_physician_id", sa.Uuid(), nullable=True),
        sa.Column("notified_physician_name", sa.String(255), nullable=True),
        sa.Column("notification_method", sa.String(16), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.Uuid(), nullable=True),
        sa.Column("escalated", sa.Boolean(), server_default="false"),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_critical_alerts_tenant", "critical_alerts", ["tenant_id"])
    op.create_index("ix_critical_alerts_order", "critical_alerts", ["order_id"])

    # --- tat_metrics ---
    op.create_table(
        "tat_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("radiology_orders.id"), nullable=False),
        sa.Column("order_to_schedule_mins", sa.Integer(), nullable=True),
        sa.Column("schedule_to_exam_mins", sa.Integer(), nullable=True),
        sa.Column("exam_to_preliminary_mins", sa.Integer(), nullable=True),
        sa.Column("exam_to_final_mins", sa.Integer(), nullable=True),
        sa.Column("final_to_distributed_mins", sa.Integer(), nullable=True),
        sa.Column("total_tat_mins", sa.Integer(), nullable=True),
        sa.Column("modality", sa.String(16), nullable=True),
        sa.Column("urgency", sa.String(16), nullable=True),
        sa.Column("is_critical", sa.Boolean(), server_default="false"),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tat_metrics_tenant", "tat_metrics", ["tenant_id"])
    op.create_index("ix_tat_metrics_order", "tat_metrics", ["order_id"])

    # --- pacs_connections ---
    op.create_table(
        "pacs_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("pacs_type", sa.String(16), nullable=False, server_default="ORTHANC"),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("dicomweb_root", sa.String(255), nullable=True),
        sa.Column("ae_title", sa.String(64), nullable=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("password", sa.String(255), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pacs_connections_tenant", "pacs_connections", ["tenant_id"])

    # --- ai_provider_configs ---
    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(64), nullable=False),
        sa.Column("api_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.String(512), nullable=True),
        sa.Column("is_certified", sa.Boolean(), server_default="false"),
        sa.Column("supported_modalities", postgresql.JSONB(), nullable=True),
        sa.Column("webhook_secret", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("priority", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_provider_configs_tenant", "ai_provider_configs", ["tenant_id"])

    # --- ai_findings ---
    op.create_table(
        "ai_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("provider_config_id", sa.Uuid(), nullable=True),
        sa.Column("finding_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("coordinates", postgresql.JSONB(), nullable=True),
        sa.Column("raw_response", postgresql.JSONB(), nullable=True),
        sa.Column("reviewed", sa.Boolean(), server_default="false"),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_findings_tenant", "ai_findings", ["tenant_id"])
    op.create_index("ix_ai_findings_order", "ai_findings", ["order_id"])

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("user_name", sa.String(255), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("patient_id", sa.Uuid(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_tenant", "audit_logs", ["tenant_id"])


def downgrade() -> None:
    tables = [
        "audit_logs",
        "ai_findings",
        "ai_provider_configs",
        "pacs_connections",
        "tat_metrics",
        "critical_alerts",
        "discrepancies",
        "peer_reviews",
        "dose_records",
        "order_billing",
        "billing_codes",
        "worklist_items",
        "report_versions",
        "radiology_reports",
        "report_templates",
        "schedule_slots",
        "radiology_orders",
    ]
    for table in tables:
        op.drop_table(table)
