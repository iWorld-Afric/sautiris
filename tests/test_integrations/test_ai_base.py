"""Tests for AI provider base classes and CAD hooks."""

from __future__ import annotations

from typing import Any

import pytest

from sautiris.integrations.ai.base import (
    AIFinding,
    AIJobResult,
    AIJobStatus,
    AIProviderAdapter,
)
from sautiris.integrations.ai.hooks import CADOverlayHooks, ViewerAnnotation

# ---------------------------------------------------------------------------
# AI Provider ABC compliance
# ---------------------------------------------------------------------------


class MockAIProvider(AIProviderAdapter):
    """Concrete test implementation of AIProviderAdapter."""

    @property
    def provider_name(self) -> str:
        return "MockCAD"

    @property
    def supported_modalities(self) -> list[str]:
        return ["CR", "CT"]

    async def submit_study(
        self,
        study_instance_uid: str,
        modality: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return f"job-{study_instance_uid}"

    async def get_status(self, job_id: str) -> AIJobStatus:
        return AIJobStatus.COMPLETED

    async def get_findings(self, job_id: str) -> AIJobResult:
        return AIJobResult(
            job_id=job_id,
            status=AIJobStatus.COMPLETED,
            findings=[
                AIFinding(
                    finding_id="f-001",
                    finding_type="nodule",
                    confidence=0.95,
                    severity="HIGH",
                )
            ],
        )

    async def health_check(self) -> dict[str, Any]:
        return {"status": "ok"}


class TestAIProviderAdapter:
    """Tests for the abstract AI provider interface."""

    def test_concrete_implementation(self) -> None:
        provider = MockAIProvider()
        assert isinstance(provider, AIProviderAdapter)

    @pytest.mark.asyncio
    async def test_submit_study(self) -> None:
        provider = MockAIProvider()
        job_id = await provider.submit_study("1.2.3.4", "CR")
        assert job_id == "job-1.2.3.4"

    @pytest.mark.asyncio
    async def test_get_status(self) -> None:
        provider = MockAIProvider()
        status = await provider.get_status("job-1")
        assert status == AIJobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_get_findings(self) -> None:
        provider = MockAIProvider()
        result = await provider.get_findings("job-1")
        assert len(result.findings) == 1
        assert result.findings[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        provider = MockAIProvider()
        health = await provider.health_check()
        assert health["status"] == "ok"

    def test_supports_modality(self) -> None:
        provider = MockAIProvider()
        assert provider.supports_modality("CR") is True
        assert provider.supports_modality("cr") is True  # Case insensitive
        assert provider.supports_modality("MR") is False


class TestAIJobStatus:
    """Tests for AIJobStatus enum."""

    def test_values(self) -> None:
        assert AIJobStatus.PENDING == "PENDING"
        assert AIJobStatus.PROCESSING == "PROCESSING"
        assert AIJobStatus.COMPLETED == "COMPLETED"
        assert AIJobStatus.FAILED == "FAILED"


class TestAIFinding:
    """Tests for AIFinding dataclass."""

    def test_defaults(self) -> None:
        finding = AIFinding()
        assert finding.confidence == 0.0
        assert finding.location == {}

    def test_with_location(self) -> None:
        finding = AIFinding(
            finding_id="f-001",
            confidence=0.92,
            location={"type": "bbox", "x": 100, "y": 200, "width": 50, "height": 50},
        )
        assert finding.location["type"] == "bbox"


# ---------------------------------------------------------------------------
# CAD Overlay Hooks
# ---------------------------------------------------------------------------


class TestCADOverlayHooks:
    """Tests for CADOverlayHooks."""

    def test_finding_to_annotation_bbox(self) -> None:
        finding = AIFinding(
            finding_id="f-001",
            study_instance_uid="1.2.3",
            series_instance_uid="4.5.6",
            sop_instance_uid="7.8.9",
            description="Nodule",
            confidence=0.95,
            location={"type": "bbox", "x": 100, "y": 200, "width": 50, "height": 50},
        )
        annotation = CADOverlayHooks.finding_to_annotation(finding)
        assert annotation is not None
        assert isinstance(annotation, ViewerAnnotation)
        assert annotation.annotation_type == "bbox"
        assert annotation.data["x"] == 100
        assert annotation.confidence == 0.95
        assert "95%" in annotation.label

    def test_finding_to_annotation_polygon(self) -> None:
        finding = AIFinding(
            finding_id="f-002",
            description="Mass",
            confidence=0.88,
            location={"type": "polygon", "points": [[0, 0], [10, 0], [10, 10]]},
        )
        annotation = CADOverlayHooks.finding_to_annotation(finding)
        assert annotation is not None
        assert annotation.annotation_type == "polygon"
        assert len(annotation.data["points"]) == 3

    def test_finding_to_annotation_no_location(self) -> None:
        finding = AIFinding(finding_id="f-003", description="General finding")
        annotation = CADOverlayHooks.finding_to_annotation(finding)
        assert annotation is None

    def test_findings_to_overlay(self) -> None:
        findings = [
            AIFinding(
                finding_id="f-001",
                study_instance_uid="1.2.3",
                description="Nodule",
                confidence=0.95,
                location={"type": "bbox", "x": 10, "y": 20, "width": 30, "height": 40},
            ),
            AIFinding(
                finding_id="f-002",
                description="Low confidence",
                confidence=0.3,
                location={"type": "bbox", "x": 50, "y": 60, "width": 10, "height": 10},
            ),
            AIFinding(
                finding_id="f-003",
                description="No location",
                confidence=0.9,
            ),
        ]
        overlay = CADOverlayHooks.findings_to_overlay(findings, min_confidence=0.5)
        assert overlay["version"] == "1.0"
        assert overlay["source"] == "sautiris-cad"
        # Only f-001 passes: f-002 below threshold, f-003 no location
        assert len(overlay["annotations"]) == 1
        assert overlay["annotations"][0]["id"] == "f-001"

    def test_findings_to_overlay_no_filter(self) -> None:
        findings = [
            AIFinding(
                finding_id="f-001",
                confidence=0.1,
                location={"type": "bbox", "x": 0, "y": 0, "width": 1, "height": 1},
            ),
        ]
        overlay = CADOverlayHooks.findings_to_overlay(findings, min_confidence=0.0)
        assert len(overlay["annotations"]) == 1

    def test_findings_to_overlay_empty(self) -> None:
        overlay = CADOverlayHooks.findings_to_overlay([])
        assert overlay["annotations"] == []
