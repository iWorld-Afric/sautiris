"""Tests for HL7v2 message builder (ORM^O01 and ORU^R01).

Verifies that built messages contain correct segments and can be
round-tripped through the parser.
"""

from __future__ import annotations

from sautiris.integrations.hl7v2.builder import build_orm_o01, build_oru_r01
from sautiris.integrations.hl7v2.parser import parse_orm_o01, parse_oru_r01

# ---------------------------------------------------------------------------
# ORM^O01 builder tests
# ---------------------------------------------------------------------------


class TestBuildOrmO01:
    """Tests for build_orm_o01."""

    def test_build_basic_order(self) -> None:
        msg = build_orm_o01(
            {
                "order_control": "NW",
                "placer_order_number": "ORD-100",
                "procedure_code": "71020",
                "procedure_description": "Chest X-Ray",
                "patient_id": "PAT-001",
                "family_name": "Doe",
                "given_name": "John",
            }
        )
        assert isinstance(msg, str)
        assert "ORM^O01" in msg
        assert "ORD-100" in msg
        assert "71020" in msg

    def test_msh_segment_present(self) -> None:
        msg = build_orm_o01({"order_control": "NW", "placer_order_number": "ORD-100"})
        assert msg.startswith("MSH|")

    def test_pid_segment_present(self) -> None:
        msg = build_orm_o01(
            {
                "patient_id": "PAT-001",
                "family_name": "Smith",
                "given_name": "Jane",
                "sex": "F",
            }
        )
        assert "PID" in msg
        assert "PAT-001" in msg

    def test_orc_segment_present(self) -> None:
        msg = build_orm_o01(
            {
                "order_control": "NW",
                "placer_order_number": "ORD-200",
            }
        )
        assert "ORC" in msg
        assert "NW" in msg

    def test_obr_segment_present(self) -> None:
        msg = build_orm_o01(
            {
                "procedure_code": "72100",
                "procedure_description": "Lumbar Spine",
            }
        )
        assert "OBR" in msg
        assert "72100" in msg

    def test_cancel_order(self) -> None:
        msg = build_orm_o01(
            {
                "order_control": "CA",
                "placer_order_number": "ORD-300",
            }
        )
        assert "CA" in msg
        assert "ORD-300" in msg

    def test_custom_message_control_id(self) -> None:
        msg = build_orm_o01(
            {"order_control": "NW"},
            message_control_id="CUSTOM-ID-001",
        )
        assert "CUSTOM-ID-001" in msg

    def test_requesting_physician(self) -> None:
        msg = build_orm_o01(
            {
                "requesting_physician_id": "DR001",
                "requesting_physician_name": "Smith",
            }
        )
        assert "DR001" in msg

    def test_round_trip_basic_fields(self) -> None:
        """Build an ORM, parse it back, verify key fields survive."""
        built = build_orm_o01(
            {
                "order_control": "NW",
                "placer_order_number": "ORD-RT-001",
                "patient_id": "PAT-RT-001",
                "family_name": "Round",
                "given_name": "Trip",
            }
        )
        parsed = parse_orm_o01(built)
        assert parsed.order_control == "NW"
        assert parsed.placer_order_number == "ORD-RT-001"
        assert parsed.patient.patient_id == "PAT-RT-001"


# ---------------------------------------------------------------------------
# ORU^R01 builder tests
# ---------------------------------------------------------------------------


class TestBuildOruR01:
    """Tests for build_oru_r01."""

    def test_build_basic_result(self) -> None:
        msg = build_oru_r01(
            report_data={
                "placer_order_number": "ORD-100",
                "filler_order_number": "FIL-100",
                "procedure_code": "71020",
                "procedure_description": "Chest X-Ray",
                "result_status": "F",
                "patient_id": "PAT-001",
            },
            observations=[
                {
                    "value_type": "TX",
                    "observation_id": "FINDINGS",
                    "observation_text": "Findings",
                    "value": "Normal chest",
                    "status": "F",
                },
            ],
        )
        assert isinstance(msg, str)
        assert "ORU^R01" in msg
        assert "ORD-100" in msg

    def test_msh_segment_present(self) -> None:
        msg = build_oru_r01(report_data={})
        assert msg.startswith("MSH|")
        assert "ORU^R01" in msg

    def test_obx_segments(self) -> None:
        msg = build_oru_r01(
            report_data={"result_status": "F"},
            observations=[
                {"value_type": "TX", "observation_id": "FIND", "value": "Finding 1"},
                {"value_type": "TX", "observation_id": "IMP", "value": "Impression 1"},
            ],
        )
        assert msg.count("OBX|") == 2

    def test_no_observations(self) -> None:
        msg = build_oru_r01(report_data={"result_status": "F"})
        assert "OBX" not in msg

    def test_custom_message_control_id(self) -> None:
        msg = build_oru_r01(
            report_data={},
            message_control_id="CUSTOM-ORU-001",
        )
        assert "CUSTOM-ORU-001" in msg

    def test_round_trip_basic_fields(self) -> None:
        """Build an ORU, parse it back, verify key fields survive."""
        built = build_oru_r01(
            report_data={
                "placer_order_number": "ORD-RT-002",
                "filler_order_number": "FIL-RT-002",
                "result_status": "F",
                "patient_id": "PAT-RT-002",
            },
            observations=[
                {
                    "set_id": "1",
                    "value_type": "TX",
                    "observation_id": "FINDINGS",
                    "observation_text": "Findings",
                    "value": "Normal",
                    "status": "F",
                },
            ],
        )
        parsed = parse_oru_r01(built)
        assert parsed.placer_order_number == "ORD-RT-002"
        assert parsed.filler_order_number == "FIL-RT-002"
        assert parsed.result_status == "F"
        assert len(parsed.observations) >= 1
