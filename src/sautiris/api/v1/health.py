"""Health check endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "sautiris"}


@router.get("/pacs")
async def pacs_health() -> dict[str, str]:
    return {"status": "not_configured"}


@router.get("/dicom")
async def dicom_health() -> dict[str, str]:
    return {"status": "not_configured"}
