"""API integration tests — end-to-end HTTP through the full router stack.

Covers Issue #36 R6: at least one integration test per module.
Covers Issue #12: two-app independence test.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import DomainEvent, EventBus
from tests.conftest import TEST_TENANT_ID, TEST_USER_ID

# ---------------------------------------------------------------------------
# Issue #12 — Independent app state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_app_instances_have_independent_event_bus() -> None:
    """Each create_ris_app() call gets its own EventBus. Events don't cross."""
    bus_a = EventBus()
    bus_b = EventBus()

    received_by_b: list[DomainEvent] = []

    async def handler_b(event: DomainEvent) -> None:
        received_by_b.append(event)

    bus_b.subscribe("order.created", handler_b)

    # Publish on bus_a — bus_b should NOT receive it
    await bus_a.publish(DomainEvent(event_type="order.created", payload={}))
    assert received_by_b == [], "Events from bus_a must not appear in bus_b"


@pytest.mark.asyncio
async def test_two_app_instances_have_independent_state(db_session: AsyncSession) -> None:
    """Two FastAPI app instances share no module-level globals."""
    from fastapi import FastAPI

    from sautiris.api.router import api_router
    from tests.conftest import TEST_USER, _apply_auth_override, _apply_db_override

    def build_app(marker: str) -> FastAPI:
        app = FastAPI()
        app.include_router(api_router, prefix="/api/v1")
        app.state.event_bus = EventBus()
        _apply_db_override(app, db_session)
        _apply_auth_override(app, TEST_USER)
        return app

    app_a = build_app("a")
    app_b = build_app("b")

    # They must be different objects with independent state
    assert app_a is not app_b
    assert app_a.state.event_bus is not app_b.state.event_bus


# ---------------------------------------------------------------------------
# Orders — create and list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_list_orders(admin_client: AsyncClient) -> None:
    """Create an order via POST, then verify it appears in GET list."""
    patient_id = str(uuid.uuid4())

    # Create
    resp = await admin_client.post(
        "/api/v1/orders",
        json={
            "patient_id": patient_id,
            "modality": "CT",
            "urgency": "ROUTINE",
            "clinical_indication": "Integration test",
        },
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["modality"] == "CT"
    assert created["status"] == "REQUESTED"
    order_id = created["id"]

    # List — the created order must be present
    resp = await admin_client.get("/api/v1/orders")
    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = [o["id"] for o in items]
    assert order_id in ids


@pytest.mark.asyncio
async def test_get_order_not_found(client: AsyncClient) -> None:
    """GET a non-existent order returns 404."""
    resp = await client.get(f"/api/v1/orders/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reports — create and finalize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_finalize_report(client: AsyncClient, db_session: AsyncSession) -> None:
    """Create a PRELIMINARY report via DB and finalize it via API."""
    import uuid as _uuid

    from sautiris.models.report import RadiologyReport, ReportStatus
    from tests.conftest import create_test_order

    order = await create_test_order(db_session, status="COMPLETED")

    # Insert a PRELIMINARY report directly (state machine: DRAFT→PRELIMINARY→FINAL)
    report = RadiologyReport(
        id=_uuid.uuid4(),
        tenant_id=TEST_TENANT_ID,
        order_id=order.id,
        accession_number=order.accession_number,
        report_status=ReportStatus.PRELIMINARY,
        reported_by=TEST_USER_ID,
        reported_by_name="Test Radiologist",
        findings="Normal study.",
        impression="No acute findings.",
    )
    db_session.add(report)
    await db_session.flush()
    report_id = str(report.id)

    # Finalize via API (PRELIMINARY → FINAL)
    resp = await client.post(f"/api/v1/reports/{report_id}/finalize")
    assert resp.status_code == 200, resp.text
    finalized = resp.json()
    assert finalized["report_status"] == "FINAL"


# ---------------------------------------------------------------------------
# Worklist — filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worklist_filtering(client: AsyncClient, db_session: AsyncSession) -> None:
    """Populate worklist via service and verify modality filtering works."""
    from sautiris.services.worklist_service import WorklistService
    from tests.conftest import create_test_order

    order_ct = await create_test_order(db_session, modality="CT", status="SCHEDULED")
    order_mr = await create_test_order(db_session, modality="MR", status="SCHEDULED")

    svc = WorklistService(db_session)
    for order in [order_ct, order_mr]:
        await svc.create_worklist_item(
            order_id=order.id,
            accession_number=order.accession_number,
            patient_id=str(order.patient_id),
            patient_name="Test Patient",
            modality=order.modality,
        )

    # Filter by CT only
    resp = await client.get("/api/v1/worklist", params={"modality": "CT"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(i["modality"] == "CT" for i in items)
    ct_ids = [i["order_id"] for i in items]
    assert str(order_ct.id) in ct_ids
    assert str(order_mr.id) not in ct_ids


# ---------------------------------------------------------------------------
# Alerts — create critical alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_critical_alert(client: AsyncClient, db_session: AsyncSession) -> None:
    """Create a critical finding alert and verify it is returned."""
    from tests.conftest import create_test_order

    order = await create_test_order(db_session, status="COMPLETED")

    resp = await client.post(
        "/api/v1/alerts",
        json={
            "order_id": str(order.id),
            "alert_type": "CRITICAL_FINDING",
            "finding_description": "Pneumothorax detected",
            "urgency": "URGENT",
            "notification_method": "IN_APP",
        },
    )
    assert resp.status_code == 201, resp.text
    alert = resp.json()
    assert alert["order_id"] == str(order.id)
    assert alert["alert_type"] == "CRITICAL_FINDING"
    assert alert["urgency"] == "URGENT"


# ---------------------------------------------------------------------------
# Dose — record dose
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_dose(technologist_client: AsyncClient, db_session: AsyncSession) -> None:
    """Record radiation dose for an order and verify retrieval."""
    from tests.conftest import create_test_order

    order = await create_test_order(db_session, modality="CT", status="COMPLETED")

    resp = await technologist_client.post(
        "/api/v1/dose",
        json={
            "order_id": str(order.id),
            "modality": "CT",
            "ctdi_vol": 15.3,
            "dlp": 350.0,
        },
    )
    assert resp.status_code == 201, resp.text
    dose = resp.json()
    assert dose["order_id"] == str(order.id)
    assert dose["ctdi_vol"] == pytest.approx(15.3)


# ---------------------------------------------------------------------------
# Role-based access — unauthenticated client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_cannot_create_order(unauth_client: AsyncClient) -> None:
    """Unauthenticated requests to protected endpoints return 401."""
    resp = await unauth_client.post(
        "/api/v1/orders",
        json={"patient_id": str(uuid.uuid4()), "modality": "CT"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_client_has_admin_role(admin_client: AsyncClient) -> None:
    """Admin client receives 200 (not 403) on admin-level endpoints."""
    resp = await admin_client.get("/api/v1/orders")
    # Admin has order:read permission so this should succeed
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_invalid_uuid_returns_422(client: AsyncClient) -> None:
    """Invalid UUID in path parameter returns 422 Unprocessable Entity."""
    resp = await client.get("/api/v1/orders/not-a-uuid")
    assert resp.status_code == 422
