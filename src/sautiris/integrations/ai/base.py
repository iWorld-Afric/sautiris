"""Abstract base class for AI provider adapters (CAD, triage, etc.)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AIJobStatus(StrEnum):
    """Status of an AI processing job."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class AIFinding:
    """A single AI-detected finding on an imaging study."""

    finding_id: str = ""
    study_instance_uid: str = ""
    series_instance_uid: str = ""
    sop_instance_uid: str = ""
    finding_type: str = ""
    description: str = ""
    confidence: float = 0.0
    severity: str = ""  # CRITICAL, HIGH, MEDIUM, LOW
    location: dict[str, Any] = field(default_factory=dict)  # bbox, polygon, etc.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AIJobResult:
    """Result of an AI processing job."""

    job_id: str = ""
    status: AIJobStatus = AIJobStatus.PENDING
    study_instance_uid: str = ""
    provider_name: str = ""
    findings: list[AIFinding] = field(default_factory=list)
    processing_time_ms: int = 0
    error_message: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


class AIProviderAdapter(ABC):
    """Abstract adapter for AI-assisted radiology providers.

    Concrete implementations should integrate with specific AI services
    such as qXR (chest X-ray), Lunit INSIGHT, CAD4TB, etc.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable name of the AI provider."""

    @property
    @abstractmethod
    def supported_modalities(self) -> list[str]:
        """List of DICOM modalities this provider can process (e.g. ['CR', 'CT'])."""

    @abstractmethod
    async def submit_study(
        self,
        study_instance_uid: str,
        modality: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Submit a study for AI analysis.

        Args:
            study_instance_uid: DICOM Study Instance UID.
            modality: Imaging modality (CR, CT, MR, etc.).
            metadata: Optional additional metadata for the AI provider.

        Returns:
            Job ID for tracking the analysis.
        """

    @abstractmethod
    async def get_status(self, job_id: str) -> AIJobStatus:
        """Check the status of a submitted AI job.

        Args:
            job_id: Job ID returned by ``submit_study``.

        Returns:
            Current job status.
        """

    @abstractmethod
    async def get_findings(self, job_id: str) -> AIJobResult:
        """Retrieve findings for a completed AI job.

        Args:
            job_id: Job ID returned by ``submit_study``.

        Returns:
            AIJobResult with findings if job is completed.

        Raises:
            RuntimeError: If the job is not yet completed.
        """

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check connectivity and health of the AI provider service.

        Returns:
            Dict with ``status`` key (``ok`` or ``error``).
        """

    def supports_modality(self, modality: str) -> bool:
        """Check if this provider supports the given modality."""
        return modality.upper() in [m.upper() for m in self.supported_modalities]
