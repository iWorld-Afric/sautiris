"""Tests for C-STORE SCP — metadata extraction and server construction.

Covers issues: #7 (25+ SOP classes, RDSR routing), #9 (transfer syntaxes).
"""

from __future__ import annotations

from types import SimpleNamespace

from sautiris.integrations.dicom.store_scp import (
    BREAST_TOMOSYNTHESIS_STORAGE,
    COMPREHENSIVE_SR_STORAGE,
    CT_IMAGE_STORAGE,
    DEFAULT_STORAGE_SOP_CLASSES,
    DIGITAL_MAMMO_STORAGE,
    ENCAPSULATED_PDF,
    ENHANCED_SR_STORAGE,
    GRAYSCALE_SOFTCOPY_PS,
    KEY_OBJECT_SELECTION,
    MR_IMAGE_STORAGE,
    NM_IMAGE_STORAGE,
    PET_IMAGE_STORAGE,
    RDSR_STORAGE,
    RF_IMAGE_STORAGE,
    RT_IMAGE_STORAGE,
    SEGMENTATION_STORAGE,
    TRANSFER_SYNTAXES,
    VL_ENDOSCOPIC_STORAGE,
    XA_IMAGE_STORAGE,
    StoreSCPServer,
    extract_store_metadata,
    is_rdsr,
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
        """Issue #7 — must have 25+ SOP classes."""
        assert len(DEFAULT_STORAGE_SOP_CLASSES) >= 25

    def test_default_bind_address(self) -> None:
        """Issue #17 — default bind must be localhost."""
        server = StoreSCPServer()
        assert server._bind_address == "127.0.0.1"


class TestIssue7SOPClasses:
    """Issue #7 — verify 25+ SOP classes including all required modalities."""

    def test_nm_image_storage(self) -> None:
        assert NM_IMAGE_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_pet_image_storage(self) -> None:
        assert PET_IMAGE_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_xa_image_storage(self) -> None:
        assert XA_IMAGE_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_rf_image_storage(self) -> None:
        assert RF_IMAGE_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_rdsr_storage(self) -> None:
        assert RDSR_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_enhanced_sr_storage(self) -> None:
        assert ENHANCED_SR_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_comprehensive_sr_storage(self) -> None:
        assert COMPREHENSIVE_SR_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_key_object_selection(self) -> None:
        assert KEY_OBJECT_SELECTION in DEFAULT_STORAGE_SOP_CLASSES

    def test_encapsulated_pdf(self) -> None:
        assert ENCAPSULATED_PDF in DEFAULT_STORAGE_SOP_CLASSES

    def test_grayscale_ps(self) -> None:
        assert GRAYSCALE_SOFTCOPY_PS in DEFAULT_STORAGE_SOP_CLASSES

    def test_rt_image_storage(self) -> None:
        assert RT_IMAGE_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_vl_endoscopic_storage(self) -> None:
        assert VL_ENDOSCOPIC_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_segmentation_storage(self) -> None:
        assert SEGMENTATION_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_digital_mammo_storage(self) -> None:
        assert DIGITAL_MAMMO_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_breast_tomosynthesis(self) -> None:
        assert BREAST_TOMOSYNTHESIS_STORAGE in DEFAULT_STORAGE_SOP_CLASSES

    def test_is_rdsr_true_for_rdsr_uid(self) -> None:
        assert is_rdsr(RDSR_STORAGE) is True

    def test_is_rdsr_false_for_ct(self) -> None:
        assert is_rdsr(CT_IMAGE_STORAGE) is False

    def test_is_rdsr_false_for_empty(self) -> None:
        assert is_rdsr("") is False


class TestIssue9TransferSyntaxes:
    """Issue #9 — 8 transfer syntaxes for C-STORE SCP."""

    def test_transfer_syntaxes_count(self) -> None:
        assert len(TRANSFER_SYNTAXES) == 8

    def test_explicit_vr_le(self) -> None:
        assert "1.2.840.10008.1.2.1" in TRANSFER_SYNTAXES

    def test_implicit_vr_le(self) -> None:
        assert "1.2.840.10008.1.2" in TRANSFER_SYNTAXES

    def test_jpeg_baseline(self) -> None:
        assert "1.2.840.10008.1.2.4.50" in TRANSFER_SYNTAXES

    def test_jpeg2000_lossless(self) -> None:
        assert "1.2.840.10008.1.2.4.90" in TRANSFER_SYNTAXES

    def test_rle_lossless(self) -> None:
        assert "1.2.840.10008.1.2.5" in TRANSFER_SYNTAXES

    def test_deflated_explicit_vr_le(self) -> None:
        assert "1.2.840.10008.1.2.1.99" in TRANSFER_SYNTAXES


# ---------------------------------------------------------------------------
# GAP-C1: _handle_store — previously had zero tests
# ---------------------------------------------------------------------------


def _make_store_event(
    sop_class_uid: str = CT_IMAGE_STORAGE,
    sop_instance_uid: str = "1.2.3.4.5",
    study_instance_uid: str = "1.2.3.4",
    series_instance_uid: str = "1.2.3.4.1",
    patient_id: str = "PAT-001",
    modality: str = "CT",
) -> SimpleNamespace:
    """Build a minimal mock pynetdicom C-STORE event.

    The event must expose:
    - event.dataset  (pydicom Dataset-like)
    - event.file_meta (pydicom file-meta-like)
    """
    ds = SimpleNamespace(
        StudyInstanceUID=study_instance_uid,
        SeriesInstanceUID=series_instance_uid,
        SOPInstanceUID=sop_instance_uid,
        SOPClassUID=sop_class_uid,
        PatientID=patient_id,
        Modality=modality,
    )

    # Patch save_as so we don't need a real pydicom Dataset
    def _save_as(buf: object, *, write_like_original: bool = False) -> None:
        if hasattr(buf, "write"):
            buf.write(b"\x00" * 16)  # type: ignore[union-attr]

    ds.save_as = _save_as  # type: ignore[attr-defined]
    file_meta = SimpleNamespace()
    return SimpleNamespace(dataset=ds, file_meta=file_meta)


class TestHandleStore:
    """GAP-C1: _handle_store method — success, failure, and RDSR routing."""

    def test_handle_store_success_returns_zero(self) -> None:
        """_handle_store with a succeeding callback returns DIMSE status 0x0000."""
        import asyncio
        import threading

        callback_received: list[tuple[bytes, dict[str, str]]] = []

        async def _ok_callback(dicom_bytes: bytes, metadata: dict) -> None:
            callback_received.append((dicom_bytes, metadata))

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = StoreSCPServer(
                store_callback=_ok_callback,
                loop=loop,
            )
            event = _make_store_event()
            status = server._handle_store(event)  # type: ignore[arg-type]

            assert status == 0x0000
            assert server.received_count == 1
            # callback must have been called with non-empty bytes and metadata
            assert len(callback_received) == 1
            _bytes, meta = callback_received[0]
            assert meta["sop_class_uid"] == CT_IMAGE_STORAGE
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()

    def test_handle_store_callback_failure_returns_c001(self) -> None:
        """_handle_store returns 0xC001 (Processing Failure) when callback raises."""
        import asyncio
        import threading

        async def _failing_callback(dicom_bytes: bytes, metadata: dict) -> None:
            raise RuntimeError("PACS write failed")

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = StoreSCPServer(
                store_callback=_failing_callback,
                loop=loop,
            )
            event = _make_store_event()
            status = server._handle_store(event)  # type: ignore[arg-type]

            assert status == 0xC001
            # received_count is still incremented (instance was counted before callback ran)
            assert server.received_count == 1
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()

    def test_handle_store_rdsr_routes_to_rdsr_callback(self) -> None:
        """RDSR SOPClassUID routes the dataset to rdsr_callback (fire-and-forget)."""
        import asyncio
        import threading

        rdsr_calls: list[tuple[object, dict]] = []
        store_calls: list[tuple[bytes, dict]] = []

        async def _rdsr_callback(dataset: object, metadata: dict) -> None:
            rdsr_calls.append((dataset, metadata))

        async def _store_callback(dicom_bytes: bytes, metadata: dict) -> None:
            store_calls.append((dicom_bytes, metadata))

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = StoreSCPServer(
                store_callback=_store_callback,
                rdsr_callback=_rdsr_callback,
                loop=loop,
            )
            rdsr_event = _make_store_event(
                sop_class_uid=RDSR_STORAGE,
                sop_instance_uid="1.2.3.rdsr.1",
                modality="SR",
            )
            status = server._handle_store(rdsr_event)  # type: ignore[arg-type]

            assert status == 0x0000
            # Give the fire-and-forget future time to complete
            import time

            time.sleep(0.1)
            assert len(rdsr_calls) == 1, "rdsr_callback should have been called once"
            _ds, meta = rdsr_calls[0]
            assert meta["sop_class_uid"] == RDSR_STORAGE
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()

    def test_handle_store_no_callback_returns_success(self) -> None:
        """When no store_callback is configured, _handle_store returns 0x0000."""
        server = StoreSCPServer(store_callback=None, loop=None)
        event = _make_store_event()
        status = server._handle_store(event)  # type: ignore[arg-type]
        assert status == 0x0000
        assert server.received_count == 1

    def test_log_rdsr_error_includes_uids(self) -> None:
        """GAP-I3: _log_rdsr_error done_callback binds sop_instance_uid and study_instance_uid.

        When the rdsr_callback raises, the structlog error() call inside the
        done_callback must include both UID keys so operators can manually
        reprocess missing dose data. We verify by replacing the module-level
        structlog logger with a capturing shim.
        """
        import asyncio
        import threading
        import time

        async def _failing_rdsr_callback(dataset: object, metadata: dict) -> None:
            raise ValueError("rdsr parse failed")

        async def _ok_store_callback(dicom_bytes: bytes, metadata: dict) -> None:
            pass

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            server = StoreSCPServer(
                store_callback=_ok_store_callback,
                rdsr_callback=_failing_rdsr_callback,
                loop=loop,
            )
            rdsr_event = _make_store_event(
                sop_class_uid=RDSR_STORAGE,
                sop_instance_uid="1.2.3.rdsr.err",
                study_instance_uid="1.2.3.study.err",
            )

            error_calls: list[tuple[tuple, dict]] = []

            import sautiris.integrations.dicom.store_scp as _store_mod

            original_logger = _store_mod.logger

            class _CapturingLogger:
                def info(self, *args: object, **kwargs: object) -> None:
                    pass

                def error(self, *args: object, **kwargs: object) -> None:
                    error_calls.append((args, kwargs))

                def warning(self, *args: object, **kwargs: object) -> None:
                    pass

                def exception(self, *args: object, **kwargs: object) -> None:
                    pass

                def debug(self, *args: object, **kwargs: object) -> None:
                    pass

            _store_mod.logger = _CapturingLogger()  # type: ignore[assignment]
            try:
                server._handle_store(rdsr_event)  # type: ignore[arg-type]
                # Allow fire-and-forget future + done_callback time to execute
                time.sleep(0.35)
            finally:
                _store_mod.logger = original_logger

            assert len(error_calls) >= 1, (
                "Expected at least one error() call from _log_rdsr_error done_callback"
            )
            event_keys = [args[0] for args, _ in error_calls if args]
            assert any("rdsr_callback_error" in str(k) for k in event_keys), (
                f"Expected 'rdsr_callback_error' event key. Got: {event_keys}"
            )
            all_kwargs_combined = {k: v for _, kw in error_calls for k, v in kw.items()}
            assert "sop_instance_uid" in all_kwargs_combined, (
                f"Expected 'sop_instance_uid' in error kwargs. Got: {all_kwargs_combined}"
            )
            assert all_kwargs_combined["sop_instance_uid"] == "1.2.3.rdsr.err"
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            loop.close()


# ---------------------------------------------------------------------------
# GAP: Store SCP timeout path
# ---------------------------------------------------------------------------


class TestStoreSCPTimeout:
    """TimeoutError in future.result() returns 0x0000 (image in-flight success)."""

    def test_timeout_returns_success_status(self) -> None:
        """When future.result() times out, _handle_store returns 0x0000 (not an error)."""
        import asyncio
        import concurrent.futures
        from unittest.mock import MagicMock, patch

        async def _slow_callback(dicom_bytes: bytes, metadata: dict) -> None:
            pass  # body irrelevant — future is fully mocked

        mock_future: MagicMock = MagicMock(spec=concurrent.futures.Future)
        mock_future.result.side_effect = concurrent.futures.TimeoutError()

        def _fake_run_coroutine_threadsafe(
            coro: object, loop: object
        ) -> MagicMock:
            # Close the coroutine to prevent ResourceWarning
            if asyncio.iscoroutine(coro):
                coro.close()  # type: ignore[union-attr]
            return mock_future

        mock_loop = MagicMock()  # truthy, passes the `if self._loop` guard

        server = StoreSCPServer(store_callback=_slow_callback, loop=mock_loop)
        event = _make_store_event()

        with patch("asyncio.run_coroutine_threadsafe", side_effect=_fake_run_coroutine_threadsafe):
            status = server._handle_store(event)  # type: ignore[arg-type]

        assert status == 0x0000
        assert server.received_count == 1
        # Confirm future.result was called with the expected timeout
        mock_future.result.assert_called_once_with(timeout=5.0)
