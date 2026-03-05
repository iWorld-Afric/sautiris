"""CAD finding hooks for viewer overlay integration.

Provides utilities to convert AI findings into viewer-compatible overlay
formats (e.g., OHIF measurement annotations, DICOM SR references).

Also includes webhook handling for async AI provider results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from sautiris.integrations.ai.base import AIFinding

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ViewerAnnotation:
    """A viewer-compatible annotation derived from an AI finding."""

    finding_id: str
    study_instance_uid: str
    series_instance_uid: str
    sop_instance_uid: str
    annotation_type: str  # "bbox", "polygon", "ellipse", "arrow"
    label: str
    confidence: float
    data: dict[str, Any]  # Annotation-specific data (coords, points, etc.)


class CADOverlayHooks:
    """Convert AI findings to viewer overlay annotations.

    Designed to produce annotations compatible with OHIF's measurement
    tracking extension and similar viewer overlay systems.
    """

    @staticmethod
    def finding_to_annotation(finding: AIFinding) -> ViewerAnnotation | None:
        """Convert a single AI finding to a viewer annotation.

        Returns None if the finding has no spatial location data.
        """
        location = finding.location
        if not location:
            logger.debug(
                "cad_hooks.no_location",
                finding_id=finding.finding_id,
                description=finding.description,
            )
            return None

        annotation_type = location.get("type", "bbox")
        data: dict[str, Any] = {}

        if annotation_type == "bbox":
            data = {
                "x": location.get("x", 0),
                "y": location.get("y", 0),
                "width": location.get("width", 0),
                "height": location.get("height", 0),
            }
        elif annotation_type == "polygon":
            data = {"points": location.get("points", [])}
        elif annotation_type == "ellipse":
            data = {
                "cx": location.get("cx", 0),
                "cy": location.get("cy", 0),
                "rx": location.get("rx", 0),
                "ry": location.get("ry", 0),
            }
        else:
            data = location

        return ViewerAnnotation(
            finding_id=finding.finding_id,
            study_instance_uid=finding.study_instance_uid,
            series_instance_uid=finding.series_instance_uid,
            sop_instance_uid=finding.sop_instance_uid,
            annotation_type=annotation_type,
            label=f"{finding.description} ({finding.confidence:.0%})",
            confidence=finding.confidence,
            data=data,
        )

    @staticmethod
    def findings_to_overlay(
        findings: list[AIFinding],
        min_confidence: float = 0.0,
    ) -> dict[str, Any]:
        """Convert a list of AI findings to a viewer overlay manifest.

        Args:
            findings: List of AI findings from a provider.
            min_confidence: Minimum confidence threshold (0.0-1.0) to include.

        Returns:
            Dict with ``annotations`` list suitable for viewer overlay rendering.
        """
        annotations: list[dict[str, Any]] = []

        for finding in findings:
            if finding.confidence < min_confidence:
                continue

            annotation = CADOverlayHooks.finding_to_annotation(finding)
            if annotation is None:
                continue

            annotations.append(
                {
                    "id": annotation.finding_id,
                    "studyInstanceUid": annotation.study_instance_uid,
                    "seriesInstanceUid": annotation.series_instance_uid,
                    "sopInstanceUid": annotation.sop_instance_uid,
                    "type": annotation.annotation_type,
                    "label": annotation.label,
                    "confidence": annotation.confidence,
                    "data": annotation.data,
                }
            )

        logger.info(
            "cad_hooks.overlay_built",
            total_findings=len(findings),
            annotations_included=len(annotations),
            min_confidence=min_confidence,
        )

        return {
            "version": "1.0",
            "source": "sautiris-cad",
            "annotations": annotations,
        }


class AIWebhookHandler:
    """Handles inbound AI provider webhook callbacks.

    Validates webhook signatures and persists AI findings from async providers.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    async def validate_webhook(
        self,
        provider_name: str,
        payload: bytes,
        signature: str,
    ) -> bool:
        """Validate webhook signature against stored provider secret."""
        import hashlib
        import hmac

        from sqlalchemy import select

        from sautiris.core.tenancy import get_current_tenant_id
        from sautiris.models.ai_integration import AIProviderConfig

        stmt = select(AIProviderConfig).where(
            AIProviderConfig.tenant_id == get_current_tenant_id(),
            AIProviderConfig.provider_name == provider_name,
            AIProviderConfig.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        config = result.scalar_one_or_none()

        if config is None or config.webhook_secret is None:
            logger.warning("ai_webhook_no_config", provider_name=provider_name)
            return False

        expected = hmac.new(
            config.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def process_webhook(
        self,
        provider_name: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Process AI provider webhook payload and persist findings."""
        import uuid

        from sqlalchemy import select

        from sautiris.core.tenancy import get_current_tenant_id
        from sautiris.models.ai_integration import AIFinding as AIFindingModel
        from sautiris.models.ai_integration import AIProviderConfig

        findings_data = payload.get("findings", [])
        order_id_str = payload.get("order_id") or payload.get("accession_number")

        if not order_id_str:
            logger.error("ai_webhook_missing_order_id", provider_name=provider_name)
            return []

        # Resolve provider config ID
        stmt = select(AIProviderConfig.id).where(
            AIProviderConfig.tenant_id == get_current_tenant_id(),
            AIProviderConfig.provider_name == provider_name,
            AIProviderConfig.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        provider_config_id = result.scalar_one_or_none()

        tenant_id = get_current_tenant_id()
        persisted: list[dict[str, Any]] = []

        for finding_data in findings_data:
            finding_model = AIFindingModel(
                tenant_id=tenant_id,
                order_id=uuid.UUID(str(order_id_str)),
                provider_config_id=provider_config_id,
                finding_type=finding_data.get("finding_type", finding_data.get("finding", "")),
                description=finding_data.get("description", ""),
                confidence=finding_data.get("confidence", finding_data.get("probability", 0.0)),
                coordinates=finding_data.get("coordinates", finding_data.get("location")),
                raw_response=finding_data,
            )
            self._session.add(finding_model)
            persisted.append(
                {"finding_type": finding_model.finding_type, "id": str(finding_model.id)}
            )

        await self._session.flush()
        await self._session.commit()
        logger.info(
            "ai_webhook_processed",
            provider_name=provider_name,
            findings_count=len(persisted),
        )
        return persisted


async def enrich_report_with_ai_findings(
    session: Any,
    order_id: Any,
) -> list[dict[str, Any]]:
    """Get AI findings for an order, formatted for report metadata overlay."""
    import uuid

    from sqlalchemy import select

    from sautiris.core.tenancy import get_current_tenant_id
    from sautiris.models.ai_integration import AIFinding as AIFindingModel

    stmt = select(AIFindingModel).where(
        AIFindingModel.tenant_id == get_current_tenant_id(),
        AIFindingModel.order_id == uuid.UUID(str(order_id)),
    )
    result = await session.execute(stmt)
    findings = list(result.scalars().all())

    overlays: list[dict[str, Any]] = []
    for finding in findings:
        overlay: dict[str, Any] = {
            "id": str(finding.id),
            "type": finding.finding_type,
            "description": finding.description,
            "confidence": finding.confidence,
            "reviewed": finding.reviewed,
        }
        if finding.coordinates:
            overlay["coordinates"] = finding.coordinates
        overlays.append(overlay)
    return overlays
