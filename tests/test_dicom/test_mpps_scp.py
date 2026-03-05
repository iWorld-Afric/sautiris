"""Tests for MPPS SCP — data extraction and server construction."""

from __future__ import annotations

from pydicom.dataset import Dataset

from sautiris.integrations.dicom.mpps_scp import (
    MPPS_SOP_CLASS,
    MPPSServer,
    extract_mpps_data,
)


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
