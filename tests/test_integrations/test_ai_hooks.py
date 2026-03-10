"""Tests for AI integration hooks — overlay builder and webhook handler."""

from __future__ import annotations

from sautiris.integrations.ai.base import AIFinding
from sautiris.integrations.ai.hooks import CADOverlayHooks


class TestCADOverlayHooks:
    def test_finding_to_annotation_bbox(self) -> None:
        finding = AIFinding(
            finding_id="f1",
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.1",
            sop_instance_uid="1.2.3.1.1",
            finding_type="nodule",
            description="Lung nodule",
            confidence=0.85,
            severity="HIGH",
            location={"type": "bbox", "x": 100, "y": 200, "width": 50, "height": 50},
        )
        annotation = CADOverlayHooks.finding_to_annotation(finding)
        assert annotation is not None
        assert annotation.annotation_type == "bbox"
        assert annotation.data["x"] == 100
        assert annotation.data["width"] == 50
        assert annotation.confidence == 0.85

    def test_finding_to_annotation_polygon(self) -> None:
        finding = AIFinding(
            finding_id="f2",
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.1",
            sop_instance_uid="1.2.3.1.1",
            finding_type="consolidation",
            description="Right lower lobe consolidation",
            confidence=0.72,
            severity="MEDIUM",
            location={"type": "polygon", "points": [[10, 20], [30, 40], [50, 60]]},
        )
        annotation = CADOverlayHooks.finding_to_annotation(finding)
        assert annotation is not None
        assert annotation.annotation_type == "polygon"
        assert len(annotation.data["points"]) == 3

    def test_finding_no_location_returns_none(self) -> None:
        finding = AIFinding(
            finding_id="f3",
            description="General abnormality",
            confidence=0.5,
        )
        annotation = CADOverlayHooks.finding_to_annotation(finding)
        assert annotation is None

    def test_findings_to_overlay(self) -> None:
        findings = [
            AIFinding(
                finding_id="f1",
                study_instance_uid="1.2.3",
                series_instance_uid="1.2.3.1",
                sop_instance_uid="1.2.3.1.1",
                description="Nodule",
                confidence=0.9,
                location={"type": "bbox", "x": 10, "y": 20, "width": 30, "height": 30},
            ),
            AIFinding(
                finding_id="f2",
                study_instance_uid="1.2.3",
                series_instance_uid="1.2.3.1",
                sop_instance_uid="1.2.3.1.2",
                description="Opacity",
                confidence=0.3,
                location={"type": "bbox", "x": 50, "y": 60, "width": 20, "height": 20},
            ),
        ]
        overlay = CADOverlayHooks.findings_to_overlay(findings, min_confidence=0.5)
        assert overlay["version"] == "1.0"
        assert len(overlay["annotations"]) == 1  # Only f1 above threshold

    def test_findings_to_overlay_all(self) -> None:
        findings = [
            AIFinding(
                finding_id=f"f{i}",
                study_instance_uid="1.2.3",
                series_instance_uid="1.2.3.1",
                sop_instance_uid=f"1.2.3.1.{i}",
                description=f"Finding {i}",
                confidence=0.8,
                location={"type": "bbox", "x": i * 10, "y": i * 10, "width": 20, "height": 20},
            )
            for i in range(3)
        ]
        overlay = CADOverlayHooks.findings_to_overlay(findings)
        assert len(overlay["annotations"]) == 3

    def test_findings_to_overlay_empty(self) -> None:
        overlay = CADOverlayHooks.findings_to_overlay([])
        assert overlay["annotations"] == []


# ---------------------------------------------------------------------------
# GAP-M4, GAP-M5: AIWebhookHandler
# ---------------------------------------------------------------------------

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from sautiris.integrations.ai.hooks import AIWebhookHandler  # noqa: E402


class TestAIWebhookHandler:
    """Tests for AIWebhookHandler webhook validation and processing."""

    async def test_validate_webhook_no_config_returns_false(
        self, db_session: AsyncSession
    ) -> None:
        """GAP-M4: validate_webhook() returns False when no AIProviderConfig exists."""
        handler = AIWebhookHandler(db_session)
        result = await handler.validate_webhook(
            provider_name="nonexistent_ai_provider_xyz",
            payload=b"test-payload",
            signature="deadbeef12345678",
        )
        assert result is False

    async def test_process_webhook_missing_order_id_raises_value_error(
        self, db_session: AsyncSession
    ) -> None:
        """GAP-M5: process_webhook() raises ValueError when order_id is absent from payload."""
        handler = AIWebhookHandler(db_session)
        with pytest.raises(ValueError):
            await handler.process_webhook(
                provider_name="test_ai_provider",
                payload={"findings": []},  # no order_id / accession_number
            )
