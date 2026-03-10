"""HL7v2 message parser for ORM^O01 (Order) and ORU^R01 (Result) messages.

Uses hl7apy for parsing and supports custom field separators from the MSH
segment. Maps parsed data to typed DTOs for internal use.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from hl7apy.core import Message
from hl7apy.parser import parse_message

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass
class HL7v2Patient:
    """Patient identity extracted from PID segment."""

    patient_id: str = ""
    family_name: str = ""
    given_name: str = ""
    date_of_birth: str = ""
    sex: str = ""
    address: str = ""
    phone: str = ""


@dataclass
class HL7v2Order:
    """Radiology order extracted from ORM^O01 message."""

    message_control_id: str = ""
    order_control: str = ""  # NW, CA, XO, etc.
    placer_order_number: str = ""
    filler_order_number: str = ""
    universal_service_id: str = ""
    universal_service_text: str = ""
    priority: str = ""
    requested_datetime: str = ""
    ordering_provider_id: str = ""
    ordering_provider_name: str = ""
    clinical_info: str = ""
    patient: HL7v2Patient = field(default_factory=HL7v2Patient)
    raw_message: str = ""


@dataclass
class HL7v2Observation:
    """Single observation from OBX segment."""

    set_id: str = ""
    value_type: str = ""
    observation_id: str = ""
    observation_text: str = ""
    value: str = ""
    units: str = ""
    abnormal_flags: str = ""
    observation_status: str = ""


@dataclass
class HL7v2Result:
    """Observation result extracted from ORU^R01 message."""

    message_control_id: str = ""
    placer_order_number: str = ""
    filler_order_number: str = ""
    universal_service_id: str = ""
    universal_service_text: str = ""
    result_status: str = ""
    observation_datetime: str = ""
    patient: HL7v2Patient = field(default_factory=HL7v2Patient)
    observations: list[HL7v2Observation] = field(default_factory=list)
    raw_message: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_get(segment: object, field_name: str, default: str = "") -> str:
    """Safely extract a string field from an hl7apy segment."""
    try:
        val = getattr(segment, field_name, None)
        if val is None:
            return default
        return str(val.value) if hasattr(val, "value") else str(val)
    except Exception:
        logger.warning("hl7v2.field_parse_error", field=field_name, exc_info=True)
        return default


def _safe_component(field_obj: object, index: int, default: str = "") -> str:
    """Safely extract a component by index from an hl7apy field."""
    try:
        children = getattr(field_obj, "children", [])
        if index < len(children):
            return (
                str(children[index].value)
                if hasattr(children[index], "value")
                else str(children[index])
            )
        return default
    except Exception:
        logger.warning("hl7v2.field_parse_error", index=index, exc_info=True)
        return default


def _parse_patient(msg: Message) -> HL7v2Patient:
    """Extract patient data from PID segment."""
    patient = HL7v2Patient()
    try:
        pid = msg.pid
    except Exception:
        logger.warning("hl7v2.patient_parse_error", exc_info=True)
        return patient

    patient.patient_id = _safe_get(pid, "pid_3")
    patient.sex = _safe_get(pid, "pid_8")
    patient.date_of_birth = _safe_get(pid, "pid_7")

    try:
        name_field = pid.pid_5
        patient.family_name = _safe_component(name_field, 0)
        patient.given_name = _safe_component(name_field, 1)
    except Exception:
        pass

    patient.address = _safe_get(pid, "pid_11")
    patient.phone = _safe_get(pid, "pid_13")
    return patient


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_orm_o01(raw: str) -> HL7v2Order:
    """Parse an ORM^O01 (Order Message) into an HL7v2Order DTO.

    Args:
        raw: Raw HL7v2 message string (segments separated by ``\\r``).

    Returns:
        Populated HL7v2Order dataclass.

    Raises:
        ValueError: If the message type is not ORM^O01.
    """
    msg = parse_message(raw, find_groups=False)

    msg_type = _safe_get(msg.msh, "msh_9")
    if "ORM" not in msg_type:
        raise ValueError(f"Expected ORM message, got: {msg_type}")

    order = HL7v2Order(raw_message=raw)
    order.message_control_id = _safe_get(msg.msh, "msh_10")

    # Patient
    order.patient = _parse_patient(msg)

    # ORC segment — order control
    try:
        orc = msg.orc
        order.order_control = _safe_get(orc, "orc_1")
        order.placer_order_number = _safe_get(orc, "orc_2")
        order.filler_order_number = _safe_get(orc, "orc_3")
        order.priority = _safe_get(orc, "orc_7")
        order.requested_datetime = _safe_get(orc, "orc_9")

        try:
            provider = orc.orc_12
            order.ordering_provider_id = _safe_component(provider, 0)
            order.ordering_provider_name = _safe_component(provider, 1)
        except Exception:
            pass
    except Exception:
        logger.warning("hl7v2.orm_missing_orc")

    # OBR segment — observation request
    try:
        obr = msg.obr
        if not order.placer_order_number:
            order.placer_order_number = _safe_get(obr, "obr_2")
        if not order.filler_order_number:
            order.filler_order_number = _safe_get(obr, "obr_3")

        try:
            service = obr.obr_4
            order.universal_service_id = _safe_component(service, 0)
            order.universal_service_text = _safe_component(service, 1)
        except Exception:
            order.universal_service_id = _safe_get(obr, "obr_4")

        order.clinical_info = _safe_get(obr, "obr_13")
        if not order.requested_datetime:
            order.requested_datetime = _safe_get(obr, "obr_6")
    except Exception:
        logger.warning("hl7v2.orm_missing_obr")

    logger.info(
        "hl7v2.parsed_orm",
        message_control_id=order.message_control_id,
        order_control=order.order_control,
        placer_order=order.placer_order_number,
    )
    return order


def parse_oru_r01(raw: str) -> HL7v2Result:
    """Parse an ORU^R01 (Observation Result) into an HL7v2Result DTO.

    Args:
        raw: Raw HL7v2 message string (segments separated by ``\\r``).

    Returns:
        Populated HL7v2Result dataclass.

    Raises:
        ValueError: If the message type is not ORU^R01.
    """
    msg = parse_message(raw, find_groups=False)

    msg_type = _safe_get(msg.msh, "msh_9")
    if "ORU" not in msg_type:
        raise ValueError(f"Expected ORU message, got: {msg_type}")

    result = HL7v2Result(raw_message=raw)
    result.message_control_id = _safe_get(msg.msh, "msh_10")

    # Patient
    result.patient = _parse_patient(msg)

    # OBR segment
    try:
        obr = msg.obr
        result.placer_order_number = _safe_get(obr, "obr_2")
        result.filler_order_number = _safe_get(obr, "obr_3")

        try:
            service = obr.obr_4
            result.universal_service_id = _safe_component(service, 0)
            result.universal_service_text = _safe_component(service, 1)
        except Exception:
            result.universal_service_id = _safe_get(obr, "obr_4")

        result.result_status = _safe_get(obr, "obr_25")
        result.observation_datetime = _safe_get(obr, "obr_7")
    except Exception:
        logger.warning("hl7v2.oru_missing_obr")

    # OBX segments
    try:
        obx_segments = msg.obx if isinstance(msg.obx, list) else [msg.obx]
    except Exception:
        obx_segments = []

    for obx in obx_segments:
        obs = HL7v2Observation()
        obs.set_id = _safe_get(obx, "obx_1")
        obs.value_type = _safe_get(obx, "obx_2")

        try:
            obs_id_field = obx.obx_3
            obs.observation_id = _safe_component(obs_id_field, 0)
            obs.observation_text = _safe_component(obs_id_field, 1)
        except Exception:
            obs.observation_id = _safe_get(obx, "obx_3")

        obs.value = _safe_get(obx, "obx_5")
        obs.units = _safe_get(obx, "obx_6")
        obs.abnormal_flags = _safe_get(obx, "obx_8")
        obs.observation_status = _safe_get(obx, "obx_11")
        result.observations.append(obs)

    logger.info(
        "hl7v2.parsed_oru",
        message_control_id=result.message_control_id,
        observation_count=len(result.observations),
    )
    return result
