"""Tests for MWL SCP — dataset conversion and query filter extraction."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from pydicom.dataset import Dataset

from sautiris.integrations.dicom.mwl_scp import (
    MWL_FIND_SOP_CLASS,
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


class TestMWLServer:
    """Tests for MWLServer construction and configuration."""

    def test_default_config(self) -> None:
        server = MWLServer()
        assert server.ae_title == "SAUTIRIS_MWL"
        assert server.port == 11112

    def test_custom_config(self) -> None:
        server = MWLServer(ae_title="MY_MWL", port=2112)
        assert server.ae_title == "MY_MWL"
        assert server.port == 2112

    def test_sop_class_uid(self) -> None:
        assert MWL_FIND_SOP_CLASS == "1.2.840.10008.5.1.4.31"
