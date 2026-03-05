"""Tests for HL7v2 message parser (ORM^O01 and ORU^R01)."""

from __future__ import annotations

import pytest

from sautiris.integrations.hl7v2.parser import (
    HL7v2Order,
    HL7v2Result,
    parse_orm_o01,
    parse_oru_r01,
)

# ---------------------------------------------------------------------------
# Sample HL7v2 messages — \r as segment separator
# ---------------------------------------------------------------------------

SAMPLE_ORM_O01 = (
    "MSH|^~\\&|SAUTICARE|HOSPITAL_A|SAUTIRIS|RIS|20260305120000||ORM^O01|MSG-001|P|2.5\r"
    "PID|||PAT-12345||DOE^JOHN||19800115|M\r"
    "ORC|NW|ORD-001||||||^R|20260305120000|||DR001^Smith^John\r"
    "OBR|1|ORD-001||71020^Chest X-Ray|||20260305120000||||||Clinical cough for 2 weeks"
)

SAMPLE_ORU_R01 = (
    "MSH|^~\\&|SAUTIRIS|RIS|SAUTICARE|HOSPITAL_A|20260305130000||ORU^R01|MSG-002|P|2.5\r"
    "PID|||PAT-12345||DOE^JOHN||19800115|M\r"
    "OBR|1|ORD-001|FIL-001|71020^Chest X-Ray|||20260305130000||||||||||||||||||F\r"
    "OBX|1|TX|FINDINGS^Findings||No acute cardiopulmonary abnormality||||||F\r"
    "OBX|2|TX|IMPRESSION^Impression||Normal chest radiograph||||||F"
)

SAMPLE_ORM_CANCEL = (
    "MSH|^~\\&|SAUTICARE|HOSPITAL_A|SAUTIRIS|RIS|20260305140000||ORM^O01|MSG-003|P|2.5\r"
    "PID|||PAT-67890||SMITH^JANE||19901225|F\r"
    "ORC|CA|ORD-002\r"
    "OBR|1|ORD-002||72100^Lumbar Spine"
)


# ---------------------------------------------------------------------------
# ORM^O01 parsing tests
# ---------------------------------------------------------------------------


class TestParseOrmO01:
    """Tests for parse_orm_o01."""

    def test_parse_basic_order(self) -> None:
        order = parse_orm_o01(SAMPLE_ORM_O01)
        assert isinstance(order, HL7v2Order)
        assert order.message_control_id == "MSG-001"
        assert order.order_control == "NW"
        assert order.placer_order_number == "ORD-001"

    def test_patient_data_extracted(self) -> None:
        order = parse_orm_o01(SAMPLE_ORM_O01)
        assert order.patient.patient_id == "PAT-12345"
        assert order.patient.sex == "M"

    def test_obr_service_id(self) -> None:
        order = parse_orm_o01(SAMPLE_ORM_O01)
        # Universal service ID should contain the procedure code
        assert "71020" in order.universal_service_id or "71020" in str(order.universal_service_text)

    def test_clinical_info(self) -> None:
        order = parse_orm_o01(SAMPLE_ORM_O01)
        assert "cough" in order.clinical_info.lower() or order.clinical_info != ""

    def test_cancel_order(self) -> None:
        order = parse_orm_o01(SAMPLE_ORM_CANCEL)
        assert order.order_control == "CA"
        assert order.placer_order_number == "ORD-002"

    def test_raw_message_preserved(self) -> None:
        order = parse_orm_o01(SAMPLE_ORM_O01)
        assert order.raw_message == SAMPLE_ORM_O01

    def test_wrong_message_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected ORM"):
            parse_orm_o01(SAMPLE_ORU_R01)


# ---------------------------------------------------------------------------
# ORU^R01 parsing tests
# ---------------------------------------------------------------------------


class TestParseOruR01:
    """Tests for parse_oru_r01."""

    def test_parse_basic_result(self) -> None:
        result = parse_oru_r01(SAMPLE_ORU_R01)
        assert isinstance(result, HL7v2Result)
        assert result.message_control_id == "MSG-002"
        assert result.placer_order_number == "ORD-001"
        assert result.filler_order_number == "FIL-001"

    def test_patient_data(self) -> None:
        result = parse_oru_r01(SAMPLE_ORU_R01)
        assert result.patient.patient_id == "PAT-12345"

    def test_observations_parsed(self) -> None:
        result = parse_oru_r01(SAMPLE_ORU_R01)
        assert len(result.observations) >= 1

    def test_observation_fields(self) -> None:
        result = parse_oru_r01(SAMPLE_ORU_R01)
        if result.observations:
            obs = result.observations[0]
            assert obs.set_id == "1"
            assert obs.value_type == "TX"

    def test_result_status(self) -> None:
        result = parse_oru_r01(SAMPLE_ORU_R01)
        assert result.result_status == "F"

    def test_raw_message_preserved(self) -> None:
        result = parse_oru_r01(SAMPLE_ORU_R01)
        assert result.raw_message == SAMPLE_ORU_R01

    def test_wrong_message_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected ORU"):
            parse_oru_r01(SAMPLE_ORM_O01)
