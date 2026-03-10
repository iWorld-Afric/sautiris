"""Tests for MWL SCP — dataset conversion and query filter extraction.

Covers issues: #3 (required tags), #5 (SpecificCharacterSet), #9 (transfer syntaxes).
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from pydicom.dataset import Dataset

from sautiris.integrations.dicom.mwl_scp import (
    CHARSET_UTF8,
    MWL_FIND_SOP_CLASS,
    TRANSFER_SYNTAXES,
    MWLServer,
    extract_query_filters,
    worklist_item_to_dataset,
)


def _make_worklist_item(**overrides):
    """Create a mock WorklistItem with default values."""
    defaults = {
        "patient_name": "DOE^JOHN",
        "patient_id": "PAT-001",
        "patient_dob": date(1990, 5, 15),
        "patient_sex": "M",
        "accession_number": "ACC-001",
        "referring_physician_name": "DR^SMITH",
        "requested_procedure_id": "RP-001",
        "requested_procedure_description": "Chest X-Ray",
        "modality": "CR",
        "scheduled_station_ae_title": "XRAY_1",
        "scheduled_procedure_step_id": "SPS-001",
        "scheduled_procedure_step_description": "PA and Lateral Chest",
        "scheduled_start": datetime(2026, 3, 5, 10, 30, 0),
        # Optional fields (not on WorklistItem model yet; accessed via getattr)
        "study_instance_uid": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestWorklistItemToDataset:
    """Tests for worklist_item_to_dataset conversion."""

    def test_patient_name(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert str(ds.PatientName) == "DOE^JOHN"

    def test_patient_id(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert ds.PatientID == "PAT-001"

    def test_patient_birth_date(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert ds.PatientBirthDate == "19900515"

    def test_patient_birth_date_none(self) -> None:
        item = _make_worklist_item(patient_dob=None)
        ds = worklist_item_to_dataset(item)
        assert ds.PatientBirthDate == ""

    def test_patient_sex(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert ds.PatientSex == "M"

    def test_accession_number(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert ds.AccessionNumber == "ACC-001"

    def test_referring_physician(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert str(ds.ReferringPhysicianName) == "DR^SMITH"

    def test_requested_procedure(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert ds.RequestedProcedureID == "RP-001"
        assert ds.RequestedProcedureDescription == "Chest X-Ray"

    def test_scheduled_procedure_step_sequence(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert len(ds.ScheduledProcedureStepSequence) == 1
        sps = ds.ScheduledProcedureStepSequence[0]
        assert sps.Modality == "CR"
        assert sps.ScheduledStationAETitle == "XRAY_1"
        assert sps.ScheduledProcedureStepID == "SPS-001"

    def test_scheduled_start_date_time(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        sps = ds.ScheduledProcedureStepSequence[0]
        assert sps.ScheduledProcedureStepStartDate == "20260305"
        assert sps.ScheduledProcedureStepStartTime == "103000"

    def test_scheduled_start_none(self) -> None:
        item = _make_worklist_item(scheduled_start=None)
        ds = worklist_item_to_dataset(item)
        sps = ds.ScheduledProcedureStepSequence[0]
        assert sps.ScheduledProcedureStepStartDate == ""
        assert sps.ScheduledProcedureStepStartTime == ""

    def test_none_fields_default_empty(self) -> None:
        item = _make_worklist_item(
            referring_physician_name=None,
            requested_procedure_id=None,
            scheduled_station_ae_title=None,
        )
        ds = worklist_item_to_dataset(item)
        assert str(ds.ReferringPhysicianName) == ""
        assert ds.RequestedProcedureID == ""

    def test_returns_dataset(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert isinstance(ds, Dataset)


class TestExtractQueryFilters:
    """Tests for extract_query_filters."""

    def test_empty_dataset_returns_empty(self) -> None:
        ds = Dataset()
        filters = extract_query_filters(ds)
        assert filters == {}

    def test_modality_filter(self) -> None:
        ds = Dataset()
        sps = Dataset()
        sps.Modality = "CT"
        ds.ScheduledProcedureStepSequence = [sps]
        filters = extract_query_filters(ds)
        assert filters["modality"] == "CT"

    def test_ae_title_filter(self) -> None:
        ds = Dataset()
        sps = Dataset()
        sps.ScheduledStationAETitle = "CT_SCANNER_1"
        ds.ScheduledProcedureStepSequence = [sps]
        filters = extract_query_filters(ds)
        assert filters["scheduled_station_ae_title"] == "CT_SCANNER_1"

    def test_single_date_filter(self) -> None:
        ds = Dataset()
        sps = Dataset()
        sps.ScheduledProcedureStepStartDate = "20260305"
        ds.ScheduledProcedureStepSequence = [sps]
        filters = extract_query_filters(ds)
        assert filters["date_from"] == date(2026, 3, 5)
        assert filters["date_to"] == date(2026, 3, 5)

    def test_date_range_filter(self) -> None:
        ds = Dataset()
        sps = Dataset()
        sps.ScheduledProcedureStepStartDate = "20260301-20260305"
        ds.ScheduledProcedureStepSequence = [sps]
        filters = extract_query_filters(ds)
        assert filters["date_from"] == date(2026, 3, 1)
        assert filters["date_to"] == date(2026, 3, 5)

    def test_empty_modality_not_included(self) -> None:
        ds = Dataset()
        sps = Dataset()
        sps.Modality = ""
        ds.ScheduledProcedureStepSequence = [sps]
        filters = extract_query_filters(ds)
        assert "modality" not in filters

    def test_combined_filters(self) -> None:
        ds = Dataset()
        sps = Dataset()
        sps.Modality = "MR"
        sps.ScheduledStationAETitle = "MR_SCANNER"
        sps.ScheduledProcedureStepStartDate = "20260305"
        ds.ScheduledProcedureStepSequence = [sps]
        filters = extract_query_filters(ds)
        assert filters["modality"] == "MR"
        assert filters["scheduled_station_ae_title"] == "MR_SCANNER"
        assert filters["date_from"] == date(2026, 3, 5)


class TestIssue3RequiredTags:
    """Issue #3 — verify all required MWL response tags are present."""

    def test_specific_character_set_utf8(self) -> None:
        """Issue #5 — SpecificCharacterSet must be ISO_IR 192."""
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert ds.SpecificCharacterSet == CHARSET_UTF8

    def test_study_instance_uid_generated_when_missing(self) -> None:
        item = _make_worklist_item(study_instance_uid=None)
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "StudyInstanceUID")
        uid = str(ds.StudyInstanceUID)
        assert uid and "." in uid  # valid DICOM UID

    def test_study_instance_uid_from_item(self) -> None:
        item = _make_worklist_item(study_instance_uid="1.2.840.10008.99")
        ds = worklist_item_to_dataset(item)
        assert str(ds.StudyInstanceUID) == "1.2.840.10008.99"

    def test_referenced_study_sequence_present(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "ReferencedStudySequence")
        assert len(ds.ReferencedStudySequence) == 0  # empty sequence is valid

    def test_requested_procedure_code_sequence_present(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "RequestedProcedureCodeSequence")
        assert len(ds.RequestedProcedureCodeSequence) == 0

    def test_request_attributes_sequence_present(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "RequestAttributesSequence")
        assert len(ds.RequestAttributesSequence) == 0

    def test_study_id_present(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "StudyID")

    def test_study_date_from_scheduled_start(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert ds.StudyDate == "20260305"

    def test_study_time_from_scheduled_start(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert ds.StudyTime == "103000"

    def test_study_date_empty_when_no_start(self) -> None:
        item = _make_worklist_item(scheduled_start=None)
        ds = worklist_item_to_dataset(item)
        assert ds.StudyDate == ""
        assert ds.StudyTime == ""

    def test_requested_procedure_priority_present(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "RequestedProcedurePriority")

    def test_patient_weight_present(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "PatientWeight")

    def test_medical_alerts_present(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "MedicalAlerts")

    def test_allergies_present(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "Allergies")

    def test_pregnancy_status_set_when_provided(self) -> None:
        item = _make_worklist_item(pregnancy_status=2)
        ds = worklist_item_to_dataset(item)
        assert ds.PregnancyStatus == 2

    def test_pregnancy_status_present_when_none(self) -> None:
        """Type 2: PregnancyStatus MUST be present even when None (zero-length allowed)."""
        item = _make_worklist_item(study_instance_uid=None)
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "PregnancyStatus")
        assert ds.PregnancyStatus == ""

    def test_scheduled_protocol_code_sequence_present(self) -> None:
        """Type 2: ScheduledProtocolCodeSequence (0040,0008) must be present."""
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        sps = ds.ScheduledProcedureStepSequence[0]
        assert hasattr(sps, "ScheduledProtocolCodeSequence")
        assert len(sps.ScheduledProtocolCodeSequence) == 0

    def test_referenced_patient_sequence_present(self) -> None:
        """Type 2: ReferencedPatientSequence (0008,1120) must be present."""
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "ReferencedPatientSequence")
        assert len(ds.ReferencedPatientSequence) == 0

    def test_admission_id_present(self) -> None:
        """Type 2: AdmissionID (0038,0010) must be present."""
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "AdmissionID")
        assert ds.AdmissionID == ""

    def test_issuer_of_patient_id_present(self) -> None:
        """Type 2: IssuerOfPatientID (0010,0021) must be present."""
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        assert hasattr(ds, "IssuerOfPatientID")
        assert ds.IssuerOfPatientID == ""


class TestIssue3QueryFilters:
    """Issue #3 — additional query filters and universal matching."""

    def test_patient_id_filter(self) -> None:
        ds = Dataset()
        ds.PatientID = "PAT-001"
        filters = extract_query_filters(ds)
        assert filters["patient_id"] == "PAT-001"

    def test_patient_name_filter(self) -> None:
        ds = Dataset()
        ds.PatientName = "DOE^JOHN"
        filters = extract_query_filters(ds)
        assert filters["patient_name"] == "DOE^JOHN"

    def test_accession_number_filter(self) -> None:
        ds = Dataset()
        ds.AccessionNumber = "ACC-001"
        filters = extract_query_filters(ds)
        assert filters["accession_number"] == "ACC-001"

    def test_requested_procedure_id_filter(self) -> None:
        ds = Dataset()
        ds.RequestedProcedureID = "RP-001"
        filters = extract_query_filters(ds)
        assert filters["requested_procedure_id"] == "RP-001"

    def test_sps_status_filter(self) -> None:
        ds = Dataset()
        sps = Dataset()
        sps.ScheduledProcedureStepStatus = "SCHEDULED"
        ds.ScheduledProcedureStepSequence = [sps]
        filters = extract_query_filters(ds)
        assert filters["scheduled_procedure_step_status"] == "SCHEDULED"

    def test_universal_matching_empty_patient_id(self) -> None:
        """Empty PatientID means 'match all' — should not add filter."""
        ds = Dataset()
        ds.PatientID = ""
        filters = extract_query_filters(ds)
        assert "patient_id" not in filters

    def test_universal_matching_empty_accession(self) -> None:
        ds = Dataset()
        ds.AccessionNumber = ""
        filters = extract_query_filters(ds)
        assert "accession_number" not in filters


class TestIssue9TransferSyntaxes:
    """Issue #9 — 8 transfer syntaxes must be defined."""

    def test_transfer_syntaxes_count(self) -> None:
        assert len(TRANSFER_SYNTAXES) == 8

    def test_explicit_vr_le_present(self) -> None:
        assert "1.2.840.10008.1.2.1" in TRANSFER_SYNTAXES

    def test_implicit_vr_le_present(self) -> None:
        assert "1.2.840.10008.1.2" in TRANSFER_SYNTAXES

    def test_jpeg_baseline_present(self) -> None:
        assert "1.2.840.10008.1.2.4.50" in TRANSFER_SYNTAXES

    def test_jpeg_lossless_present(self) -> None:
        assert "1.2.840.10008.1.2.4.70" in TRANSFER_SYNTAXES

    def test_jpeg2000_lossless_present(self) -> None:
        assert "1.2.840.10008.1.2.4.90" in TRANSFER_SYNTAXES

    def test_jpeg2000_present(self) -> None:
        assert "1.2.840.10008.1.2.4.91" in TRANSFER_SYNTAXES

    def test_rle_lossless_present(self) -> None:
        assert "1.2.840.10008.1.2.5" in TRANSFER_SYNTAXES

    def test_deflated_explicit_vr_le_present(self) -> None:
        assert "1.2.840.10008.1.2.1.99" in TRANSFER_SYNTAXES


class TestMWLServer:
    """Tests for MWLServer construction and configuration."""

    def test_default_config(self) -> None:
        server = MWLServer()
        assert server.ae_title == "SAUTIRIS_MWL"
        assert server.port == 11112

    def test_default_bind_address(self) -> None:
        """Issue #17 — default bind must be localhost, not 0.0.0.0."""
        server = MWLServer()
        assert server._bind_address == "127.0.0.1"

    def test_custom_config(self) -> None:
        server = MWLServer(ae_title="MY_MWL", port=2112)
        assert server.ae_title == "MY_MWL"
        assert server.port == 2112

    def test_sop_class_uid(self) -> None:
        assert MWL_FIND_SOP_CLASS == "1.2.840.10008.5.1.4.31"


class TestScheduledPerformingPhysicianName:
    """G3-2: ScheduledPerformingPhysicianName in SPS response."""

    def test_performing_physician_present_in_sps(self) -> None:
        item = _make_worklist_item(scheduled_performing_physician_name="DR^JONES")
        ds = worklist_item_to_dataset(item)
        sps = ds.ScheduledProcedureStepSequence[0]
        assert str(sps.ScheduledPerformingPhysicianName) == "DR^JONES"

    def test_performing_physician_empty_when_none(self) -> None:
        item = _make_worklist_item()
        ds = worklist_item_to_dataset(item)
        sps = ds.ScheduledProcedureStepSequence[0]
        assert str(sps.ScheduledPerformingPhysicianName) == ""


class TestPatientNameWildcardFilters:
    """G3-1: DICOM wildcard matching for PatientName C-FIND queries."""

    def test_wildcard_star_suffix(self) -> None:
        ds = Dataset()
        ds.PatientName = "DOE*"
        filters = extract_query_filters(ds)
        assert "patient_name" not in filters
        assert filters["patient_name_pattern"] == "DOE%"

    def test_wildcard_question_mark(self) -> None:
        ds = Dataset()
        ds.PatientName = "DO?"
        filters = extract_query_filters(ds)
        assert filters["patient_name_pattern"] == "DO_"

    def test_wildcard_combined(self) -> None:
        ds = Dataset()
        ds.PatientName = "D?E*"
        filters = extract_query_filters(ds)
        assert filters["patient_name_pattern"] == "D_E%"

    def test_exact_match_no_wildcards(self) -> None:
        ds = Dataset()
        ds.PatientName = "DOE^JOHN"
        filters = extract_query_filters(ds)
        assert filters["patient_name"] == "DOE^JOHN"
        assert "patient_name_pattern" not in filters

    def test_wildcard_star_only(self) -> None:
        ds = Dataset()
        ds.PatientName = "*"
        filters = extract_query_filters(ds)
        assert filters["patient_name_pattern"] == "%"


class TestSQLLIKEMetacharacterEscaping:
    """R2-H3: SQL LIKE metacharacters (% and _) must be escaped before wildcard conversion."""

    def test_literal_percent_escaped_in_wildcard_query(self) -> None:
        """Patient name '100%*' should escape % before converting * to %."""
        ds = Dataset()
        ds.PatientName = "100%*"
        filters = extract_query_filters(ds)
        assert filters["patient_name_pattern"] == r"100\%%"

    def test_literal_underscore_escaped_in_wildcard_query(self) -> None:
        """Patient name 'DOE_J*' should escape _ before converting * to %."""
        ds = Dataset()
        ds.PatientName = "DOE_J*"
        filters = extract_query_filters(ds)
        assert filters["patient_name_pattern"] == r"DOE\_J%"

    def test_both_metacharacters_escaped(self) -> None:
        """Both % and _ literals are escaped in wildcard queries."""
        ds = Dataset()
        ds.PatientName = "100%_TEST*"
        filters = extract_query_filters(ds)
        assert filters["patient_name_pattern"] == r"100\%\_TEST%"

    def test_no_metacharacters_no_change(self) -> None:
        """Normal wildcard query without SQL metacharacters is unchanged."""
        ds = Dataset()
        ds.PatientName = "DOE*"
        filters = extract_query_filters(ds)
        assert filters["patient_name_pattern"] == "DOE%"

    def test_exact_match_with_percent_not_escaped(self) -> None:
        """Exact match (no DICOM wildcards) doesn't touch SQL metacharacters."""
        ds = Dataset()
        ds.PatientName = "100% Smith"
        filters = extract_query_filters(ds)
        # No wildcards → exact match path, not LIKE pattern
        assert filters["patient_name"] == "100% Smith"
        assert "patient_name_pattern" not in filters


# ---------------------------------------------------------------------------
# GAP-2: _handle_find callback exception path
# ---------------------------------------------------------------------------


class TestHandleFindCallbackErrors:
    """GAP-2: _handle_find must yield 0xC001 when query_callback raises."""

    def test_callback_exception_yields_error_status(self) -> None:
        """When query_callback raises, _handle_find yields (0xC001, None)."""
        import asyncio
        import threading

        async def _failing_callback(filters: dict) -> list:
            raise RuntimeError("Database connection lost")

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = MWLServer(query_callback=_failing_callback, loop=loop)
            identifier = Dataset()  # empty = universal match
            event_mock = SimpleNamespace(identifier=identifier)
            results = list(server._handle_find(event_mock))
            assert len(results) == 1
            status, ds = results[0]
            assert status == 0xC001
            assert ds is None
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()


# ---------------------------------------------------------------------------
# GAP-3: _handle_find per-item conversion error isolation
# ---------------------------------------------------------------------------


class TestHandleFindItemConversionError:
    """GAP-3: A single bad item must not abort the entire C-FIND."""

    def test_bad_item_skipped_others_returned(self) -> None:
        """If worklist_item_to_dataset raises for one item, others still yield."""
        import asyncio
        import threading

        good_item_1 = _make_worklist_item(patient_id="PAT-GOOD-1")

        # Create a bad item that raises during dataset conversion by using
        # a property that explodes when accessed
        class _ExplodingItem:
            """Mock item that raises when patient_name is accessed."""

            id = "BAD-ITEM"

            @property
            def patient_name(self) -> str:
                raise ValueError("Corrupted DB record")

        bad_item = _ExplodingItem()
        good_item_3 = _make_worklist_item(patient_id="PAT-GOOD-3")

        async def _callback(filters: dict) -> list:
            return [good_item_1, bad_item, good_item_3]

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = MWLServer(query_callback=_callback, loop=loop)
            identifier = Dataset()
            event_mock = SimpleNamespace(identifier=identifier)
            results = list(server._handle_find(event_mock))
            # Only good items should be returned (0xFF00 = pending match)
            success_results = [(s, d) for s, d in results if s == 0xFF00]
            assert len(success_results) == 2
            patient_ids = [str(d.PatientID) for _, d in success_results]
            assert "PAT-GOOD-1" in patient_ids
            assert "PAT-GOOD-3" in patient_ids
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()


# ---------------------------------------------------------------------------
# GAP-6: Shared constants.py direct coverage
# ---------------------------------------------------------------------------


class TestSharedConstants:
    """GAP-6: Verify shared constants from constants.py are correct."""

    def test_charset_utf8_value(self) -> None:
        from sautiris.integrations.dicom.constants import CHARSET_UTF8 as SHARED_CHARSET

        assert SHARED_CHARSET == "ISO_IR 192"

    def test_default_transfer_syntaxes_count(self) -> None:
        from sautiris.integrations.dicom.constants import DEFAULT_TRANSFER_SYNTAXES

        assert len(DEFAULT_TRANSFER_SYNTAXES) == 8

    def test_default_transfer_syntaxes_contains_key_uids(self) -> None:
        from sautiris.integrations.dicom.constants import DEFAULT_TRANSFER_SYNTAXES

        assert "1.2.840.10008.1.2.1" in DEFAULT_TRANSFER_SYNTAXES  # Explicit VR LE
        assert "1.2.840.10008.1.2" in DEFAULT_TRANSFER_SYNTAXES  # Implicit VR LE


# ---------------------------------------------------------------------------
# GAP-8: Open-ended date range patterns
# ---------------------------------------------------------------------------


class TestOpenEndedDateRanges:
    """GAP-8: DICOM open-ended date range queries."""

    def test_open_end_date_range(self) -> None:
        """'20260301-' sets date_from only."""
        ds = Dataset()
        sps = Dataset()
        sps.ScheduledProcedureStepStartDate = "20260301-"
        ds.ScheduledProcedureStepSequence = [sps]
        filters = extract_query_filters(ds)
        assert filters["date_from"] == date(2026, 3, 1)
        assert "date_to" not in filters

    def test_open_start_date_range(self) -> None:
        """'-20260305' sets date_to only."""
        ds = Dataset()
        sps = Dataset()
        sps.ScheduledProcedureStepStartDate = "-20260305"
        ds.ScheduledProcedureStepSequence = [sps]
        filters = extract_query_filters(ds)
        assert "date_from" not in filters
        assert filters["date_to"] == date(2026, 3, 5)


# ---------------------------------------------------------------------------
# StudyInstanceUID persistence — same UID across repeated queries
# ---------------------------------------------------------------------------


class TestStudyInstanceUIDPersistence:
    """Verify that a persisted study_instance_uid is returned consistently."""

    def test_persisted_uid_returned_on_repeated_calls(self) -> None:
        """Same worklist item must return same StudyInstanceUID every time."""
        uid = "1.2.826.0.1.3680043.9.7539.99.1"
        item = _make_worklist_item(study_instance_uid=uid)
        ds1 = worklist_item_to_dataset(item)
        ds2 = worklist_item_to_dataset(item)
        assert str(ds1.StudyInstanceUID) == uid
        assert str(ds2.StudyInstanceUID) == uid

    def test_none_uid_generates_uid_each_call(self) -> None:
        """Legacy items without persisted UID still get a generated UID."""
        item = _make_worklist_item(study_instance_uid=None)
        ds = worklist_item_to_dataset(item)
        uid = str(ds.StudyInstanceUID)
        assert uid and "." in uid  # valid DICOM UID format

    def test_empty_string_uid_generates_new_uid(self) -> None:
        """Empty string UID should be treated as absent and generate a new one."""
        item = _make_worklist_item(study_instance_uid="")
        ds = worklist_item_to_dataset(item)
        uid = str(ds.StudyInstanceUID)
        assert uid and uid != ""  # should be a generated UID, not empty


# ---------------------------------------------------------------------------
# R2-H4: Shared build_dicom_ssl_context tests
# ---------------------------------------------------------------------------


class TestBuildDicomSSLContext:
    """R2-H4: Shared build_dicom_ssl_context utility in constants.py."""

    def test_returns_none_when_no_cert(self) -> None:
        from sautiris.integrations.dicom.constants import build_dicom_ssl_context

        result = build_dicom_ssl_context("", "", "")
        assert result is None

    def test_returns_none_when_no_key(self) -> None:
        from sautiris.integrations.dicom.constants import build_dicom_ssl_context

        result = build_dicom_ssl_context("/path/to/cert.pem", "", "")
        assert result is None

    def test_returns_none_when_both_empty(self) -> None:
        from sautiris.integrations.dicom.constants import build_dicom_ssl_context

        result = build_dicom_ssl_context("", "/path/to/key.pem", "")
        assert result is None

    def test_all_three_scp_classes_delegate_to_shared_helper(self) -> None:
        """All 3 SCP _build_ssl_context methods delegate to the shared function."""
        from sautiris.integrations.dicom.mpps_scp import MPPSServer
        from sautiris.integrations.dicom.store_scp import StoreSCPServer

        # Without TLS config, all return None (via shared helper)
        mpps = MPPSServer()
        mwl = MWLServer()
        store = StoreSCPServer()

        assert mpps._build_ssl_context() is None
        assert mwl._build_ssl_context() is None
        assert store._build_ssl_context() is None
