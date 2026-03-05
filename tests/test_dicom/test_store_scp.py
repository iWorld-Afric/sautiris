"""Tests for C-STORE SCP — metadata extraction and server construction."""

from __future__ import annotations

from types import SimpleNamespace

from sautiris.integrations.dicom.store_scp import (
    CT_IMAGE_STORAGE,
    DEFAULT_STORAGE_SOP_CLASSES,
    MR_IMAGE_STORAGE,
    StoreSCPServer,
    extract_store_metadata,
)


class TestExtractStoreMetadata:
    """Tests for extract_store_metadata."""

    def test_full_metadata(self) -> None:
        ds = SimpleNamespace(
            StudyInstanceUID="1.2.3",
            SeriesInstanceUID="4.5.6",
            SOPInstanceUID="7.8.9",
            SOPClassUID=CT_IMAGE_STORAGE,
            PatientID="PAT-001",
            Modality="CT",
        )
        metadata = extract_store_metadata(ds)
        assert metadata["study_instance_uid"] == "1.2.3"
        assert metadata["series_instance_uid"] == "4.5.6"
        assert metadata["sop_instance_uid"] == "7.8.9"
        assert metadata["sop_class_uid"] == CT_IMAGE_STORAGE
        assert metadata["patient_id"] == "PAT-001"
        assert metadata["modality"] == "CT"

    def test_missing_attributes(self) -> None:
        ds = SimpleNamespace()
        metadata = extract_store_metadata(ds)
        assert metadata["study_instance_uid"] == ""
        assert metadata["patient_id"] == ""
        assert metadata["modality"] == ""

    def test_partial_attributes(self) -> None:
        ds = SimpleNamespace(
            StudyInstanceUID="1.2.3",
            Modality="MR",
        )
        metadata = extract_store_metadata(ds)
        assert metadata["study_instance_uid"] == "1.2.3"
        assert metadata["modality"] == "MR"
        assert metadata["sop_instance_uid"] == ""


class TestStoreSCPServer:
    """Tests for StoreSCPServer construction."""

    def test_default_config(self) -> None:
        server = StoreSCPServer()
        assert server.ae_title == "SAUTIRIS_STORE"
        assert server.port == 11114

    def test_custom_config(self) -> None:
        server = StoreSCPServer(ae_title="MY_STORE", port=4114)
        assert server.ae_title == "MY_STORE"
        assert server.port == 4114

    def test_received_count_initially_zero(self) -> None:
        server = StoreSCPServer()
        assert server.received_count == 0

    def test_default_sop_classes(self) -> None:
        server = StoreSCPServer()
        assert CT_IMAGE_STORAGE in server._storage_sop_classes
        assert MR_IMAGE_STORAGE in server._storage_sop_classes

    def test_custom_sop_classes(self) -> None:
        server = StoreSCPServer(storage_sop_classes=[CT_IMAGE_STORAGE])
        assert server._storage_sop_classes == [CT_IMAGE_STORAGE]

    def test_default_storage_sop_classes_count(self) -> None:
        assert len(DEFAULT_STORAGE_SOP_CLASSES) == 8
