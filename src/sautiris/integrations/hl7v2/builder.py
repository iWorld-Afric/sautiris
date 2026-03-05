"""HL7v2 message builder for ORM^O01 (Order) and ORU^R01 (Result) messages.

Constructs valid HL7v2 messages from internal data structures for outbound
interoperability with HIS, LIS, and PACS systems.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from hl7apy.core import Message

logger = structlog.get_logger(__name__)

# HL7v2 timestamp format
HL7_TS_FMT = "%Y%m%d%H%M%S"

# Application identity
SENDING_APP = "SAUTIRIS"
SENDING_FACILITY = "SAUTIRIS_FACILITY"


def _ts_now() -> str:
    """Current timestamp in HL7v2 format."""
    return datetime.now(UTC).strftime(HL7_TS_FMT)


def _set_msh(
    msg: Message,
    message_type: str,
    trigger_event: str,
    message_control_id: str,
    receiving_app: str = "",
    receiving_facility: str = "",
) -> None:
    """Populate the MSH segment with standard header fields."""
    msg.msh.msh_3 = SENDING_APP
    msg.msh.msh_4 = SENDING_FACILITY
    msg.msh.msh_5 = receiving_app
    msg.msh.msh_6 = receiving_facility
    msg.msh.msh_7 = _ts_now()
    msg.msh.msh_9 = f"{message_type}^{trigger_event}"
    msg.msh.msh_10 = message_control_id
    msg.msh.msh_11 = "P"  # Processing ID: Production
    msg.msh.msh_12 = "2.5"  # Version ID


def _set_pid(
    msg: Message,
    patient_id: str = "",
    family_name: str = "",
    given_name: str = "",
    dob: str = "",
    sex: str = "",
) -> None:
    """Populate the PID segment with patient demographics."""
    msg.add_segment("PID")
    pid = msg.pid
    pid.pid_3 = patient_id
    pid.pid_5 = f"{family_name}^{given_name}"
    if dob:
        pid.pid_7 = dob
    if sex:
        pid.pid_8 = sex


def build_orm_o01(
    order_data: dict[str, Any],
    message_control_id: str = "",
    receiving_app: str = "",
    receiving_facility: str = "",
) -> str:
    """Build an ORM^O01 (General Order) message.

    Args:
        order_data: Dict with keys:

            - ``order_control``: ORC-1 (NW=new, CA=cancel, XO=change)
            - ``placer_order_number``: ORC-2 / OBR-2
            - ``filler_order_number``: ORC-3 / OBR-3 (optional)
            - ``procedure_code``: OBR-4 component 1
            - ``procedure_description``: OBR-4 component 2
            - ``priority``: ORC-7 (R=routine, S=stat, A=ASAP, T=timing critical)
            - ``clinical_info``: OBR-13
            - ``requesting_physician_id``: ORC-12 component 1
            - ``requesting_physician_name``: ORC-12 component 2
            - ``patient_id``, ``family_name``, ``given_name``, ``dob``, ``sex``

        message_control_id: MSH-10 unique message ID. Auto-generated if empty.
        receiving_app: MSH-5 receiving application.
        receiving_facility: MSH-6 receiving facility.

    Returns:
        Encoded HL7v2 message string with ``\\r`` segment separators.
    """
    if not message_control_id:
        message_control_id = f"SRIS-{_ts_now()}"

    msg = Message("ORM_O01", version="2.5")
    _set_msh(msg, "ORM", "O01", message_control_id, receiving_app, receiving_facility)

    # PID
    _set_pid(
        msg,
        patient_id=order_data.get("patient_id", ""),
        family_name=order_data.get("family_name", ""),
        given_name=order_data.get("given_name", ""),
        dob=order_data.get("dob", ""),
        sex=order_data.get("sex", ""),
    )

    # ORC — Common Order
    msg.add_segment("ORC")
    orc = msg.orc
    orc.orc_1 = order_data.get("order_control", "NW")
    orc.orc_2 = order_data.get("placer_order_number", "")
    if order_data.get("filler_order_number"):
        orc.orc_3 = order_data["filler_order_number"]
    if order_data.get("priority"):
        orc.orc_7 = order_data["priority"]
    orc.orc_9 = _ts_now()
    if order_data.get("requesting_physician_id"):
        physician_id = order_data["requesting_physician_id"]
        physician_name = order_data.get("requesting_physician_name", "")
        orc.orc_12 = f"{physician_id}^{physician_name}"

    # OBR — Observation Request
    msg.add_segment("OBR")
    obr = msg.obr
    obr.obr_1 = "1"
    obr.obr_2 = order_data.get("placer_order_number", "")
    if order_data.get("filler_order_number"):
        obr.obr_3 = order_data["filler_order_number"]

    proc_code = order_data.get("procedure_code", "")
    proc_desc = order_data.get("procedure_description", "")
    obr.obr_4 = f"{proc_code}^{proc_desc}"

    obr.obr_6 = _ts_now()
    if order_data.get("clinical_info"):
        obr.obr_13 = order_data["clinical_info"]

    encoded = msg.to_er7()
    logger.info(
        "hl7v2.built_orm",
        message_control_id=message_control_id,
        order_control=order_data.get("order_control", "NW"),
    )
    return str(encoded)


def build_oru_r01(
    report_data: dict[str, Any],
    observations: list[dict[str, Any]] | None = None,
    message_control_id: str = "",
    receiving_app: str = "",
    receiving_facility: str = "",
) -> str:
    """Build an ORU^R01 (Observation Result) message.

    Args:
        report_data: Dict with keys:

            - ``placer_order_number``: OBR-2
            - ``filler_order_number``: OBR-3
            - ``procedure_code``: OBR-4 component 1
            - ``procedure_description``: OBR-4 component 2
            - ``result_status``: OBR-25 (F=final, P=preliminary)
            - ``patient_id``, ``family_name``, ``given_name``, ``dob``, ``sex``

        observations: List of dicts, each with:

            - ``set_id``: OBX-1
            - ``value_type``: OBX-2 (TX, NM, CE, etc.)
            - ``observation_id``: OBX-3 component 1
            - ``observation_text``: OBX-3 component 2
            - ``value``: OBX-5
            - ``units``: OBX-6
            - ``abnormal_flags``: OBX-8
            - ``status``: OBX-11 (F, P, etc.)

        message_control_id: MSH-10 unique message ID. Auto-generated if empty.
        receiving_app: MSH-5 receiving application.
        receiving_facility: MSH-6 receiving facility.

    Returns:
        Encoded HL7v2 message string with ``\\r`` segment separators.
    """
    if not message_control_id:
        message_control_id = f"SRIS-{_ts_now()}"

    msg = Message("ORU_R01", version="2.5")
    _set_msh(msg, "ORU", "R01", message_control_id, receiving_app, receiving_facility)

    # PID
    _set_pid(
        msg,
        patient_id=report_data.get("patient_id", ""),
        family_name=report_data.get("family_name", ""),
        given_name=report_data.get("given_name", ""),
        dob=report_data.get("dob", ""),
        sex=report_data.get("sex", ""),
    )

    # OBR — Observation Request
    msg.add_segment("OBR")
    obr = msg.obr
    obr.obr_1 = "1"
    obr.obr_2 = report_data.get("placer_order_number", "")
    if report_data.get("filler_order_number"):
        obr.obr_3 = report_data["filler_order_number"]

    proc_code = report_data.get("procedure_code", "")
    proc_desc = report_data.get("procedure_description", "")
    obr.obr_4 = f"{proc_code}^{proc_desc}"

    obr.obr_7 = _ts_now()
    if report_data.get("result_status"):
        obr.obr_25 = report_data["result_status"]

    # OBX segments
    for i, obs in enumerate(observations or [], start=1):
        msg.add_segment("OBX")
        obx = msg.children[-1]  # Get the just-added OBX
        obx.obx_1 = str(obs.get("set_id", i))
        obx.obx_2 = obs.get("value_type", "TX")
        obs_id = obs.get("observation_id", "")
        obs_text = obs.get("observation_text", "")
        obx.obx_3 = f"{obs_id}^{obs_text}"
        obx.obx_5 = obs.get("value", "")
        if obs.get("units"):
            obx.obx_6 = obs["units"]
        if obs.get("abnormal_flags"):
            obx.obx_8 = obs["abnormal_flags"]
        obx.obx_11 = obs.get("status", "F")

    encoded = msg.to_er7()
    logger.info(
        "hl7v2.built_oru",
        message_control_id=message_control_id,
        observation_count=len(observations or []),
    )
    return str(encoded)
