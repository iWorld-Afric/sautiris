"""Tests for MPPS SCP — data extraction, state machine, and server construction.

Covers issues: #5 (SpecificCharacterSet), #9 (transfer syntaxes),
#14 (MPPS state machine validation).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from pydicom.dataset import Dataset

from sautiris.integrations.dicom.mpps_scp import (
    CHARSET_UTF8,
    MPPS_SOP_CLASS,
    MPPS_STATUS_COMPLETED,
    MPPS_STATUS_DISCONTINUED,
    MPPS_STATUS_IN_PROGRESS,
    TRANSFER_SYNTAXES,
    MPPSServer,
    extract_mpps_data,
)
from sautiris.models.mpps import MPPSStatusEnum


class TestExtractMPPSData:
    """Tests for extract_mpps_data."""

    def test_empty_dataset(self) -> None:
        ds = Dataset()
        data = extract_mpps_data(ds)
        assert data == {}

    def test_status_in_progress(self) -> None:
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "IN PROGRESS"
        data = extract_mpps_data(ds)
        assert data["mpps_status"] == "IN PROGRESS"

    def test_status_completed(self) -> None:
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "COMPLETED"
        data = extract_mpps_data(ds)
        assert data["mpps_status"] == "COMPLETED"

    def test_status_discontinued(self) -> None:
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "DISCONTINUED"
        data = extract_mpps_data(ds)
        assert data["mpps_status"] == "DISCONTINUED"

    def test_performed_procedure_step_id(self) -> None:
        ds = Dataset()
        ds.PerformedProcedureStepID = "PPS-001"
        data = extract_mpps_data(ds)
        assert data["performed_procedure_step_id"] == "PPS-001"

    def test_performed_station_ae_title(self) -> None:
        ds = Dataset()
        ds.PerformedStationAETitle = "CT_SCANNER_1"
        data = extract_mpps_data(ds)
        assert data["performed_station_ae_title"] == "CT_SCANNER_1"

    def test_accession_number_from_scheduled_step(self) -> None:
        ds = Dataset()
        step = Dataset()
        step.AccessionNumber = "ACC-001"
        ds.ScheduledStepAttributesSequence = [step]
        data = extract_mpps_data(ds)
        assert data["accession_number"] == "ACC-001"

    def test_study_uid_from_scheduled_step(self) -> None:
        ds = Dataset()
        step = Dataset()
        step.StudyInstanceUID = "1.2.3.4.5"
        ds.ScheduledStepAttributesSequence = [step]
        data = extract_mpps_data(ds)
        assert data["study_instance_uid"] == "1.2.3.4.5"

    def test_full_mpps_dataset(self) -> None:
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "COMPLETED"
        ds.PerformedProcedureStepID = "PPS-002"
        ds.PerformedStationAETitle = "MR_1"
        step = Dataset()
        step.AccessionNumber = "ACC-002"
        step.StudyInstanceUID = "1.2.3.4.6"
        ds.ScheduledStepAttributesSequence = [step]

        data = extract_mpps_data(ds)
        assert data["mpps_status"] == "COMPLETED"
        assert data["performed_procedure_step_id"] == "PPS-002"
        assert data["performed_station_ae_title"] == "MR_1"
        assert data["accession_number"] == "ACC-002"
        assert data["study_instance_uid"] == "1.2.3.4.6"

    def test_empty_scheduled_step_sequence(self) -> None:
        ds = Dataset()
        ds.ScheduledStepAttributesSequence = []
        data = extract_mpps_data(ds)
        assert "accession_number" not in data

    def test_strips_whitespace(self) -> None:
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "  COMPLETED  "
        data = extract_mpps_data(ds)
        assert data["mpps_status"] == "COMPLETED"


class TestMPPSServer:
    """Tests for MPPSServer construction."""

    def test_default_config(self) -> None:
        server = MPPSServer()
        assert server.ae_title == "SAUTIRIS_MPPS"
        assert server.port == 11113

    def test_custom_config(self) -> None:
        server = MPPSServer(ae_title="MY_MPPS", port=3113)
        assert server.ae_title == "MY_MPPS"
        assert server.port == 3113

    def test_instances_initially_empty(self) -> None:
        server = MPPSServer()
        assert server._instances == {}

    def test_sop_class_uid(self) -> None:
        assert MPPS_SOP_CLASS == "1.2.840.10008.3.1.2.3.3"

    def test_default_bind_address(self) -> None:
        """Issue #17 — default bind must be localhost, not 0.0.0.0."""
        server = MPPSServer()
        assert server._bind_address == "127.0.0.1"


def _make_n_create_event(sop_uid: str, status: str = "IN PROGRESS") -> MagicMock:
    """Build a mock pynetdicom EVT_N_CREATE event."""
    attr_list = Dataset()
    attr_list.PerformedProcedureStepStatus = status
    attr_list.PerformedProcedureStepID = "PPS-TEST"
    attr_list.PerformedStationAETitle = "TEST_AE"
    attr_list.PerformedProcedureStepStartDate = "20260310"
    attr_list.PerformedProcedureStepStartTime = "100000"
    request = MagicMock()
    request.AffectedSOPInstanceUID = sop_uid
    event = MagicMock()
    event.attribute_list = attr_list
    event.request = request
    return event


def _make_n_set_event(sop_uid: str, new_status: str) -> MagicMock:
    """Build a mock pynetdicom EVT_N_SET event."""
    from pydicom.sequence import Sequence as DicomSeq

    mod_list = Dataset()
    mod_list.PerformedProcedureStepStatus = new_status
    if new_status in ("COMPLETED", MPPSStatusEnum.COMPLETED):
        mod_list.PerformedProcedureStepEndDate = "20260310"
        mod_list.PerformedProcedureStepEndTime = "160000"
    elif new_status in ("DISCONTINUED", MPPSStatusEnum.DISCONTINUED):
        mod_list.PerformedProcedureStepEndDate = "20260310"
        mod_list.PerformedProcedureStepEndTime = "160000"
        # PS3.4 F.7.2 — DiscontinuationReasonCodeSequence required
        reason_item = Dataset()
        reason_item.CodeValue = "110514"
        reason_item.CodingSchemeDesignator = "DCM"
        reason_item.CodeMeaning = "Equipment failure"
        mod_list.PerformedProcedureStepDiscontinuationReasonCodeSequence = DicomSeq([reason_item])
    request = MagicMock()
    request.RequestedSOPInstanceUID = sop_uid
    event = MagicMock()
    event.modification_list = mod_list
    event.request = request
    return event


class TestIssue14MPPSStateMachine:
    """Issue #14 — MPPS state machine validation."""

    def test_n_create_in_progress_succeeds(self) -> None:
        server = MPPSServer()
        event = _make_n_create_event("1.2.3.4.1", MPPS_STATUS_IN_PROGRESS)
        status, _ds = server._handle_n_create(event)
        assert status == 0x0000
        assert "1.2.3.4.1" in server._instances

    def test_n_create_wrong_status_rejected(self) -> None:
        """N-CREATE with status other than IN PROGRESS must return 0x0110."""
        server = MPPSServer()
        event = _make_n_create_event("1.2.3.4.2", MPPS_STATUS_COMPLETED)
        status, ds = server._handle_n_create(event)
        assert status == 0x0110
        assert ds is None
        assert "1.2.3.4.2" not in server._instances

    def test_n_create_duplicate_rejected(self) -> None:
        """Duplicate N-CREATE for existing UID must return 0x0111."""
        server = MPPSServer()
        uid = "1.2.3.4.3"
        event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)
        server._handle_n_create(event)  # first create — OK
        status, ds = server._handle_n_create(event)  # duplicate
        assert status == 0x0111
        assert ds is None

    def test_n_set_to_completed_succeeds(self) -> None:
        server = MPPSServer()
        uid = "1.2.3.4.4"
        server._handle_n_create(_make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS))
        status, _ds = server._handle_n_set(_make_n_set_event(uid, MPPS_STATUS_COMPLETED))
        assert status == 0x0000

    def test_n_set_to_discontinued_succeeds(self) -> None:
        server = MPPSServer()
        uid = "1.2.3.4.5"
        server._handle_n_create(_make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS))
        status, _ds = server._handle_n_set(_make_n_set_event(uid, MPPS_STATUS_DISCONTINUED))
        assert status == 0x0000

    def test_n_set_unknown_uid_rejected(self) -> None:
        """N-SET for unknown SOP UID must return 0x0110."""
        server = MPPSServer()
        event = _make_n_set_event("9.9.9.9.9", MPPS_STATUS_COMPLETED)
        status, ds = server._handle_n_set(event)
        assert status == 0x0110
        assert ds is None

    def test_n_set_invalid_target_status_rejected(self) -> None:
        """N-SET with unexpected status must return 0x0110."""
        server = MPPSServer()
        uid = "1.2.3.4.6"
        server._handle_n_create(_make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS))
        # Try to set to an invalid target status
        status, ds = server._handle_n_set(_make_n_set_event(uid, "IN PROGRESS"))
        assert status == 0x0110

    def test_n_set_from_terminal_state_rejected(self) -> None:
        """Second N-SET after COMPLETED must return 0x0110 (terminal state)."""
        server = MPPSServer()
        uid = "1.2.3.4.7"
        server._handle_n_create(_make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS))
        server._handle_n_set(_make_n_set_event(uid, MPPS_STATUS_COMPLETED))
        # Try to set again from completed
        status, ds = server._handle_n_set(_make_n_set_event(uid, MPPS_STATUS_DISCONTINUED))
        assert status == 0x0110


class TestIssue5CharsetMPPS:
    """Issue #5 — MPPS response datasets must carry SpecificCharacterSet."""

    def test_n_create_response_has_charset(self) -> None:
        server = MPPSServer()
        event = _make_n_create_event("1.2.3.charset.1", MPPS_STATUS_IN_PROGRESS)
        _status, response = server._handle_n_create(event)
        assert response is not None
        assert response.SpecificCharacterSet == CHARSET_UTF8

    def test_n_set_response_has_charset(self) -> None:
        server = MPPSServer()
        uid = "1.2.3.charset.2"
        server._handle_n_create(_make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS))
        _status, response = server._handle_n_set(_make_n_set_event(uid, MPPS_STATUS_COMPLETED))
        assert response is not None
        assert response.SpecificCharacterSet == CHARSET_UTF8


class TestIssue9TransferSyntaxesMPPS:
    """Issue #9 — 8 transfer syntaxes for MPPS SCP."""

    def test_transfer_syntaxes_count(self) -> None:
        assert len(TRANSFER_SYNTAXES) == 8

    def test_explicit_vr_le(self) -> None:
        assert "1.2.840.10008.1.2.1" in TRANSFER_SYNTAXES

    def test_implicit_vr_le(self) -> None:
        assert "1.2.840.10008.1.2" in TRANSFER_SYNTAXES


# ---------------------------------------------------------------------------
# GAP-9: _invoke_callback error handling — HIGH-4 regression
# ---------------------------------------------------------------------------


class TestInvokeCallbackErrorHandling:
    """_invoke_callback failure must propagate DIMSE status 0xC001 to the SCU.

    Before HIGH-4 fix, a callback exception was swallowed and the DIMSE status
    returned as success (0x0000).  Now the handler returns 0xC001 on failure.
    """

    def test_callback_failure_on_n_create_returns_processing_error(self) -> None:
        """_invoke_callback raising → _handle_n_create returns 0xC001."""
        import asyncio
        import threading

        async def _failing_callback(mpps_uid: str, mpps_data: dict) -> None:
            raise RuntimeError("DB write failed")

        # run_coroutine_threadsafe requires the loop to be running in a thread
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = MPPSServer(status_callback=_failing_callback, loop=loop)
            uid = "1.2.3.callback.error.1"
            event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)
            status, ds = server._handle_n_create(event)

            assert status == 0xC001
            assert ds is None
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()

    def test_callback_success_on_n_create_returns_zero(self) -> None:
        """_invoke_callback succeeding → _handle_n_create returns 0x0000."""
        import asyncio
        import threading

        async def _ok_callback(mpps_uid: str, mpps_data: dict) -> None:
            pass  # success

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = MPPSServer(status_callback=_ok_callback, loop=loop)
            uid = "1.2.3.callback.ok.1"
            event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)
            status, ds = server._handle_n_create(event)

            assert status == 0x0000
            assert ds is not None
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()

    def test_no_callback_configured_returns_success(self) -> None:
        """When no callback is configured, _invoke_callback returns True → success."""
        server = MPPSServer(status_callback=None, loop=None)
        uid = "1.2.3.no.callback.1"
        event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)
        status, ds = server._handle_n_create(event)

        assert status == 0x0000
        assert ds is not None

    def test_callback_failure_on_n_set_returns_processing_error(self) -> None:
        """GAP-I4: callback raising during N-SET → _handle_n_set returns 0xC001.

        Before the fix, N-SET callback exceptions were swallowed. Now 0xC001
        must be returned so the modality knows the MPPS update was not persisted.
        """
        import asyncio
        import threading

        async def _failing_callback(mpps_uid: str, mpps_data: dict) -> None:
            raise RuntimeError("DB write failed on N-SET")

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            # Create instance with no-callback server to seed the state machine
            seed_server = MPPSServer(status_callback=None, loop=None)
            uid = "1.2.3.nset.callback.fail.1"
            create_event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)
            c_status, _ = seed_server._handle_n_create(create_event)
            assert c_status == 0x0000

            # Build the failing server and inject the seeded instance
            failing_server = MPPSServer(status_callback=_failing_callback, loop=loop)
            failing_server._instances[uid] = seed_server._instances[uid]

            # N-SET with a callback that will fail
            set_event = _make_n_set_event(uid, MPPS_STATUS_COMPLETED)
            status, ds = failing_server._handle_n_set(set_event)

            assert status == 0xC001
            assert ds is None
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()

    def test_callback_success_on_n_set_returns_zero(self) -> None:
        """GAP-I4: callback succeeding during N-SET → _handle_n_set returns 0x0000."""
        import asyncio
        import threading

        async def _ok_callback(mpps_uid: str, mpps_data: dict) -> None:
            pass  # success

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = MPPSServer(status_callback=_ok_callback, loop=loop)
            uid = "1.2.3.nset.callback.ok.1"
            create_event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)
            c_status, _ = server._handle_n_create(create_event)
            assert c_status == 0x0000

            set_event = _make_n_set_event(uid, MPPS_STATUS_COMPLETED)
            status, ds = server._handle_n_set(set_event)

            assert status == 0x0000
            assert ds is not None
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()


class TestIssue14RequiredAttributes:
    """PS3.4 F.7.2 — required Type 1 attributes on N-CREATE and N-SET."""

    def test_n_create_missing_step_id_rejected(self) -> None:
        """N-CREATE without PerformedProcedureStepID → 0x0110."""
        server = MPPSServer()
        attr_list = Dataset()
        attr_list.PerformedProcedureStepStatus = "IN PROGRESS"
        attr_list.PerformedStationAETitle = "CT_1"
        attr_list.PerformedProcedureStepStartDate = "20260310"
        attr_list.PerformedProcedureStepStartTime = "143000"
        # PerformedProcedureStepID deliberately missing
        request = MagicMock()
        request.AffectedSOPInstanceUID = "1.2.3.attr.1"
        event = MagicMock()
        event.attribute_list = attr_list
        event.request = request
        status, ds = server._handle_n_create(event)
        assert status == 0x0110
        assert ds is None

    def test_n_create_missing_ae_title_rejected(self) -> None:
        server = MPPSServer()
        attr_list = Dataset()
        attr_list.PerformedProcedureStepStatus = "IN PROGRESS"
        attr_list.PerformedProcedureStepID = "PPS-001"
        attr_list.PerformedProcedureStepStartDate = "20260310"
        attr_list.PerformedProcedureStepStartTime = "143000"
        # PerformedStationAETitle deliberately missing
        request = MagicMock()
        request.AffectedSOPInstanceUID = "1.2.3.attr.2"
        event = MagicMock()
        event.attribute_list = attr_list
        event.request = request
        status, ds = server._handle_n_create(event)
        assert status == 0x0110

    def test_n_create_all_required_attrs_succeeds(self) -> None:
        server = MPPSServer()
        event = _make_n_create_event("1.2.3.attr.3", MPPS_STATUS_IN_PROGRESS)
        status, ds = server._handle_n_create(event)
        assert status == 0x0000
        assert ds is not None

    def test_n_set_completed_missing_end_date_rejected(self) -> None:
        server = MPPSServer()
        server._handle_n_create(_make_n_create_event("1.2.3.attr.4", MPPS_STATUS_IN_PROGRESS))
        # N-SET to COMPLETED without end date/time
        mod_list = Dataset()
        mod_list.PerformedProcedureStepStatus = "COMPLETED"
        # Deliberately missing end date and time
        request = MagicMock()
        request.RequestedSOPInstanceUID = "1.2.3.attr.4"
        event = MagicMock()
        event.modification_list = mod_list
        event.request = request
        status, ds = server._handle_n_set(event)
        assert status == 0x0110

    def test_n_set_completed_with_end_date_succeeds(self) -> None:
        server = MPPSServer()
        server._handle_n_create(_make_n_create_event("1.2.3.attr.5", MPPS_STATUS_IN_PROGRESS))
        event = _make_n_set_event("1.2.3.attr.5", MPPS_STATUS_COMPLETED)
        status, ds = server._handle_n_set(event)
        assert status == 0x0000
        assert ds is not None

    def test_n_set_discontinued_missing_end_date_rejected(self) -> None:
        """PS3.4 F.7.2: DISCONTINUED requires end date/time — reject if missing."""
        server = MPPSServer()
        server._handle_n_create(_make_n_create_event("1.2.3.attr.6", MPPS_STATUS_IN_PROGRESS))
        # Manually build N-SET without end date/time
        mod_list = Dataset()
        mod_list.PerformedProcedureStepStatus = "DISCONTINUED"
        # Missing: PerformedProcedureStepEndDate, EndTime, DiscontinuationReason
        request = MagicMock()
        request.RequestedSOPInstanceUID = "1.2.3.attr.6"
        event = MagicMock()
        event.modification_list = mod_list
        event.request = request
        status, ds = server._handle_n_set(event)
        assert status == 0x0110
        assert ds is None

    def test_n_set_discontinued_missing_reason_seq_rejected(self) -> None:
        """PS3.4 F.7.2: DISCONTINUED requires DiscontinuationReasonCodeSequence."""
        server = MPPSServer()
        server._handle_n_create(_make_n_create_event("1.2.3.attr.7", MPPS_STATUS_IN_PROGRESS))
        mod_list = Dataset()
        mod_list.PerformedProcedureStepStatus = "DISCONTINUED"
        mod_list.PerformedProcedureStepEndDate = "20260310"
        mod_list.PerformedProcedureStepEndTime = "160000"
        # Missing: PerformedProcedureStepDiscontinuationReasonCodeSequence
        request = MagicMock()
        request.RequestedSOPInstanceUID = "1.2.3.attr.7"
        event = MagicMock()
        event.modification_list = mod_list
        event.request = request
        status, ds = server._handle_n_set(event)
        assert status == 0x0110
        assert ds is None

    def test_n_set_discontinued_empty_reason_seq_rejected(self) -> None:
        """PS3.4 F.7.2: empty DiscontinuationReasonCodeSequence is invalid."""
        from pydicom.sequence import Sequence as DicomSeq

        server = MPPSServer()
        server._handle_n_create(_make_n_create_event("1.2.3.attr.8", MPPS_STATUS_IN_PROGRESS))
        mod_list = Dataset()
        mod_list.PerformedProcedureStepStatus = "DISCONTINUED"
        mod_list.PerformedProcedureStepEndDate = "20260310"
        mod_list.PerformedProcedureStepEndTime = "160000"
        mod_list.PerformedProcedureStepDiscontinuationReasonCodeSequence = DicomSeq()  # empty
        request = MagicMock()
        request.RequestedSOPInstanceUID = "1.2.3.attr.8"
        event = MagicMock()
        event.modification_list = mod_list
        event.request = request
        status, ds = server._handle_n_set(event)
        assert status == 0x0110
        assert ds is None

    def test_n_set_discontinued_with_all_required_succeeds(self) -> None:
        """PS3.4 F.7.2: DISCONTINUED with end date/time and reason succeeds."""
        server = MPPSServer()
        server._handle_n_create(_make_n_create_event("1.2.3.attr.9", MPPS_STATUS_IN_PROGRESS))
        event = _make_n_set_event("1.2.3.attr.9", MPPS_STATUS_DISCONTINUED)
        status, ds = server._handle_n_set(event)
        assert status == 0x0000
        assert ds is not None


class TestPreloadActiveInstances:
    """Test preload_active_instances for DB recovery on startup."""

    def test_preload_populates_instances(self) -> None:
        server = MPPSServer()
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "IN PROGRESS"
        server.preload_active_instances({"1.2.3.preload.1": ds})
        assert "1.2.3.preload.1" in server._instances

    def test_preloaded_instance_allows_n_set(self) -> None:
        server = MPPSServer()
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "IN PROGRESS"
        server.preload_active_instances({"1.2.3.preload.2": ds})
        event = _make_n_set_event("1.2.3.preload.2", MPPS_STATUS_COMPLETED)
        status, _ = server._handle_n_set(event)
        assert status == 0x0000

    def test_preload_empty_dict(self) -> None:
        server = MPPSServer()
        server.preload_active_instances({})
        assert server._instances == {}


# ---------------------------------------------------------------------------
# GAP-1: _validate_required_attrs empty-string branch
# ---------------------------------------------------------------------------


class TestValidateRequiredAttrsEmptyStrings:
    """GAP-1: _validate_required_attrs must reject empty/whitespace-only Type 1 attrs."""

    def test_n_create_empty_step_id_rejected(self) -> None:
        """N-CREATE with empty string PerformedProcedureStepID → 0x0110."""
        server = MPPSServer()
        attr_list = Dataset()
        attr_list.PerformedProcedureStepStatus = "IN PROGRESS"
        attr_list.PerformedProcedureStepID = ""
        attr_list.PerformedStationAETitle = "CT_1"
        attr_list.PerformedProcedureStepStartDate = "20260310"
        attr_list.PerformedProcedureStepStartTime = "143000"
        request = MagicMock()
        request.AffectedSOPInstanceUID = "1.2.3.gap1.1"
        event = MagicMock()
        event.attribute_list = attr_list
        event.request = request
        status, ds = server._handle_n_create(event)
        assert status == 0x0110
        assert ds is None

    def test_n_create_whitespace_only_step_id_rejected(self) -> None:
        """N-CREATE with whitespace-only PerformedProcedureStepID → 0x0110."""
        server = MPPSServer()
        attr_list = Dataset()
        attr_list.PerformedProcedureStepStatus = "IN PROGRESS"
        attr_list.PerformedProcedureStepID = "   "
        attr_list.PerformedStationAETitle = "CT_1"
        attr_list.PerformedProcedureStepStartDate = "20260310"
        attr_list.PerformedProcedureStepStartTime = "143000"
        request = MagicMock()
        request.AffectedSOPInstanceUID = "1.2.3.gap1.2"
        event = MagicMock()
        event.attribute_list = attr_list
        event.request = request
        status, ds = server._handle_n_create(event)
        assert status == 0x0110

    def test_n_set_completed_empty_end_date_rejected(self) -> None:
        """N-SET to COMPLETED with empty PerformedProcedureStepEndDate → 0x0110."""
        server = MPPSServer()
        server._handle_n_create(_make_n_create_event("1.2.3.gap1.3", MPPS_STATUS_IN_PROGRESS))
        mod_list = Dataset()
        mod_list.PerformedProcedureStepStatus = "COMPLETED"
        mod_list.PerformedProcedureStepEndDate = ""
        mod_list.PerformedProcedureStepEndTime = "160000"
        request = MagicMock()
        request.RequestedSOPInstanceUID = "1.2.3.gap1.3"
        event = MagicMock()
        event.modification_list = mod_list
        event.request = request
        status, ds = server._handle_n_set(event)
        assert status == 0x0110


# ---------------------------------------------------------------------------
# GAP-5: preload_active_instances edge cases
# ---------------------------------------------------------------------------


class TestPreloadEdgeCases:
    """GAP-5: preload_active_instances overwrite and terminal-state behavior."""

    def test_preloaded_uid_blocks_duplicate_n_create(self) -> None:
        """Preloaded UID should block N-CREATE (duplicate detection — 0x0111)."""
        server = MPPSServer()
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "IN PROGRESS"
        server.preload_active_instances({"1.2.3.gap5.1": ds})
        event = _make_n_create_event("1.2.3.gap5.1", MPPS_STATUS_IN_PROGRESS)
        status, _ = server._handle_n_create(event)
        assert status == 0x0111

    def test_preloaded_terminal_state_blocks_n_set(self) -> None:
        """Preloaded COMPLETED instance should block N-SET (terminal state)."""
        server = MPPSServer()
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "COMPLETED"
        server.preload_active_instances({"1.2.3.gap5.2": ds})
        event = _make_n_set_event("1.2.3.gap5.2", MPPS_STATUS_DISCONTINUED)
        status, _ = server._handle_n_set(event)
        assert status == 0x0110


# ---------------------------------------------------------------------------
# GAP-7: _current_status with corrupted status value
# ---------------------------------------------------------------------------


class TestCurrentStatusCorruptedValue:
    """GAP-7: _current_status returns None for invalid status, blocking N-SET."""

    def test_corrupted_status_rejects_n_set(self) -> None:
        """Stored dataset with invalid status string → N-SET returns 0x0110."""
        server = MPPSServer()
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "GARBAGE"
        server._instances["1.2.3.gap7.1"] = ds
        event = _make_n_set_event("1.2.3.gap7.1", MPPS_STATUS_COMPLETED)
        status, _ = server._handle_n_set(event)
        assert status == 0x0110


# ---------------------------------------------------------------------------
# R2-C3: N-CREATE rollback _instances on callback failure
# ---------------------------------------------------------------------------


class TestNCreateCallbackRollback:
    """R2-C3: _instances must be rolled back when N-CREATE callback fails."""

    def test_instances_empty_after_failed_callback(self) -> None:
        """Failed callback → SOP UID removed from _instances (no phantom state)."""
        import asyncio
        import threading

        async def _failing_callback(mpps_uid: str, mpps_data: dict) -> None:
            raise RuntimeError("DB write failed")

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = MPPSServer(status_callback=_failing_callback, loop=loop)
            uid = "1.2.3.rollback.1"
            event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)
            status, ds = server._handle_n_create(event)

            assert status == 0xC001
            assert ds is None
            # The critical assertion: instance must NOT remain in memory
            assert uid not in server._instances
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()

    def test_successful_callback_keeps_instance(self) -> None:
        """Successful callback → SOP UID remains in _instances."""
        import asyncio
        import threading

        async def _ok_callback(mpps_uid: str, mpps_data: dict) -> None:
            pass

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = MPPSServer(status_callback=_ok_callback, loop=loop)
            uid = "1.2.3.rollback.2"
            event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)
            status, ds = server._handle_n_create(event)

            assert status == 0x0000
            assert uid in server._instances
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()

    def test_retry_n_create_after_rollback_succeeds(self) -> None:
        """After failed N-CREATE + rollback, retrying the same UID must succeed."""
        import asyncio
        import threading

        call_count = 0

        async def _fail_then_succeed(mpps_uid: str, mpps_data: dict) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = MPPSServer(status_callback=_fail_then_succeed, loop=loop)
            uid = "1.2.3.rollback.3"
            event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)

            # First attempt fails
            status1, _ = server._handle_n_create(event)
            assert status1 == 0xC001
            assert uid not in server._instances

            # Retry succeeds (not rejected as duplicate)
            status2, ds2 = server._handle_n_create(event)
            assert status2 == 0x0000
            assert ds2 is not None
            assert uid in server._instances
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()


# ---------------------------------------------------------------------------
# R2-H8: N-SET working copy preservation — stored instance unchanged on failure
# ---------------------------------------------------------------------------


class TestNSetWorkingCopyPreservation:
    """R2-H8: N-SET callback failure must not mutate the stored instance."""

    def test_stored_instance_unchanged_after_failed_nset_callback(self) -> None:
        """Stored dataset status remains IN PROGRESS after failed N-SET callback."""
        import asyncio
        import threading

        async def _failing_callback(mpps_uid: str, mpps_data: dict) -> None:
            raise RuntimeError("DB write failed on N-SET")

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            # Seed an IN PROGRESS instance with no-callback server
            seed_server = MPPSServer(status_callback=None, loop=None)
            uid = "1.2.3.working.copy.1"
            create_event = _make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS)
            c_status, _ = seed_server._handle_n_create(create_event)
            assert c_status == 0x0000

            # Build a failing server with the seeded instance
            failing_server = MPPSServer(status_callback=_failing_callback, loop=loop)
            failing_server._instances[uid] = seed_server._instances[uid]

            # Attempt N-SET to COMPLETED (callback will fail)
            set_event = _make_n_set_event(uid, MPPS_STATUS_COMPLETED)
            status, ds = failing_server._handle_n_set(set_event)

            assert status == 0xC001
            assert ds is None

            # The stored instance must still have status IN PROGRESS
            stored = failing_server._instances[uid]
            stored_status = str(getattr(stored, "PerformedProcedureStepStatus", "")).strip()
            assert stored_status == "IN PROGRESS"

            # The stored dataset should not have gained end date/time from the N-SET
            assert not getattr(stored, "PerformedProcedureStepEndDate", None)
            assert not getattr(stored, "PerformedProcedureStepEndTime", None)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()

    def test_stored_instance_updated_after_successful_nset_callback(self) -> None:
        """After successful N-SET, stored dataset reflects new COMPLETED status."""
        server = MPPSServer()
        uid = "1.2.3.working.copy.2"
        server._handle_n_create(_make_n_create_event(uid, MPPS_STATUS_IN_PROGRESS))
        server._handle_n_set(_make_n_set_event(uid, MPPS_STATUS_COMPLETED))

        stored = server._instances[uid]
        stored_status = str(getattr(stored, "PerformedProcedureStepStatus", "")).strip()
        assert stored_status == "COMPLETED"
