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

    def test_pregnancy_status_absent_when_none(self) -> None:
        item = _make_worklist_item(study_instance_uid=None)
        ds = worklist_item_to_dataset(item)
        # Not set when None — no attribute
        assert not hasattr(ds, "PregnancyStatus")


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
