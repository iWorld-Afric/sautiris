"""Tests for DICOM Association Security (Issue #17).

Covers: AE title whitelist (with wildcards), connection limiting, IP rate limiting.
"""

from __future__ import annotations

import pytest

from sautiris.integrations.dicom.security import DicomAssociationSecurity


class TestAETitleWhitelist:
    """AE title whitelist enforcement."""

    def test_no_whitelist_allows_all(self) -> None:
        sec = DicomAssociationSecurity(ae_whitelist=None)
        assert sec.is_ae_allowed("ANY_AE") is True
        assert sec.is_ae_allowed("RANDOM") is True

    def test_empty_whitelist_denies_all(self) -> None:
        sec = DicomAssociationSecurity(ae_whitelist=[])
        assert sec.is_ae_allowed("CT_SCANNER") is False

    def test_exact_match_allowed(self) -> None:
        sec = DicomAssociationSecurity(ae_whitelist=["CT_SCANNER_1", "MR_UNIT"])
        assert sec.is_ae_allowed("CT_SCANNER_1") is True
        assert sec.is_ae_allowed("MR_UNIT") is True

    def test_not_in_whitelist_rejected(self) -> None:
        sec = DicomAssociationSecurity(ae_whitelist=["CT_SCANNER_1"])
        assert sec.is_ae_allowed("US_MACHINE") is False

    def test_wildcard_pattern_allowed(self) -> None:
        sec = DicomAssociationSecurity(ae_whitelist=["CT_SCANNER_*"])
        assert sec.is_ae_allowed("CT_SCANNER_1") is True
        assert sec.is_ae_allowed("CT_SCANNER_2") is True
        assert sec.is_ae_allowed("MR_1") is False

    def test_multiple_patterns(self) -> None:
        sec = DicomAssociationSecurity(ae_whitelist=["CT_*", "MR_*"])
        assert sec.is_ae_allowed("CT_A") is True
        assert sec.is_ae_allowed("MR_B") is True
        assert sec.is_ae_allowed("US_C") is False

    def test_leading_trailing_whitespace_stripped(self) -> None:
        sec = DicomAssociationSecurity(ae_whitelist=["CT_SCANNER"])
        assert sec.is_ae_allowed("  CT_SCANNER  ") is True


class TestConnectionLimit:
    """Per-IP concurrent connection limiting."""

    def test_acquire_within_limit(self) -> None:
        sec = DicomAssociationSecurity(max_connections_per_ip=3)
        assert sec.acquire_connection("10.0.0.1") is True
        assert sec.acquire_connection("10.0.0.1") is True
        assert sec.acquire_connection("10.0.0.1") is True

    def test_acquire_exceeds_limit(self) -> None:
        sec = DicomAssociationSecurity(max_connections_per_ip=2)
        sec.acquire_connection("10.0.0.1")
        sec.acquire_connection("10.0.0.1")
        assert sec.acquire_connection("10.0.0.1") is False

    def test_release_frees_slot(self) -> None:
        sec = DicomAssociationSecurity(max_connections_per_ip=1)
        sec.acquire_connection("10.0.0.1")
        assert sec.acquire_connection("10.0.0.1") is False
        sec.release_connection("10.0.0.1")
        assert sec.acquire_connection("10.0.0.1") is True

    def test_check_connection_limit_predicate(self) -> None:
        sec = DicomAssociationSecurity(max_connections_per_ip=2)
        assert sec.check_connection_limit("10.0.0.2") is True
        sec.acquire_connection("10.0.0.2")
        sec.acquire_connection("10.0.0.2")
        assert sec.check_connection_limit("10.0.0.2") is False

    def test_different_ips_independent(self) -> None:
        sec = DicomAssociationSecurity(max_connections_per_ip=1)
        sec.acquire_connection("10.0.0.1")
        # Different IP should still be allowed
        assert sec.acquire_connection("10.0.0.2") is True

    def test_release_below_zero_is_safe(self) -> None:
        sec = DicomAssociationSecurity(max_connections_per_ip=5)
        # Release without prior acquire — should not go negative
        sec.release_connection("10.0.0.1")
        assert sec.active_connections.get("10.0.0.1", 0) == 0


class TestRateLimit:
    """Per-IP rate limiting (sliding window)."""

    def test_within_rate_limit_allowed(self) -> None:
        sec = DicomAssociationSecurity(rate_limit_per_minute=5)
        for _ in range(5):
            assert sec.check_rate_limit("10.0.0.1") is True

    def test_exceeds_rate_limit_denied(self) -> None:
        sec = DicomAssociationSecurity(rate_limit_per_minute=3)
        sec.check_rate_limit("10.0.0.1")
        sec.check_rate_limit("10.0.0.1")
        sec.check_rate_limit("10.0.0.1")
        assert sec.check_rate_limit("10.0.0.1") is False

    def test_different_ips_independent_rate(self) -> None:
        sec = DicomAssociationSecurity(rate_limit_per_minute=1)
        sec.check_rate_limit("10.0.0.1")  # exhaust IP 1
        assert sec.check_rate_limit("10.0.0.1") is False
        # Different IP should be fresh
        assert sec.check_rate_limit("10.0.0.2") is True


class TestActiveConnectionsSnapshot:
    """active_connections property returns a snapshot."""

    def test_initial_snapshot_empty(self) -> None:
        sec = DicomAssociationSecurity()
        assert sec.active_connections == {}

    def test_snapshot_after_acquire(self) -> None:
        sec = DicomAssociationSecurity()
        sec.acquire_connection("10.0.0.1")
        sec.acquire_connection("10.0.0.1")
        snap = sec.active_connections
        assert snap["10.0.0.1"] == 2

    def test_snapshot_is_copy(self) -> None:
        sec = DicomAssociationSecurity()
        sec.acquire_connection("10.0.0.1")
        snap = sec.active_connections
        snap["10.0.0.1"] = 999  # mutate snapshot
        assert sec.active_connections["10.0.0.1"] == 1  # original unchanged


# ---------------------------------------------------------------------------
# GAP-8: handle_association_request() EVT handler tests (CRITICAL-3 regression)
# ---------------------------------------------------------------------------


def _make_event(ae_title: str = "CT_SCANNER_1", ip: str = "10.0.0.1") -> object:
    """Build a minimal mock pynetdicom Event for association request tests."""
    from unittest.mock import MagicMock

    assoc = MagicMock()
    assoc.requestor.ae_title = ae_title
    assoc.requestor.address = ip
    event = MagicMock()
    event.assoc = assoc
    return event


def _make_broken_event() -> object:
    """Build a mock event where AE/IP extraction raises an exception.

    Uses real Python classes so that attribute access actually raises
    AttributeError (MagicMock auto-creates attributes, so PropertyMock
    approaches do not reliably trigger the exception path).
    """

    class _BrokenRequestor:
        @property
        def ae_title(self) -> str:
            raise AttributeError("ae_title not available in this context")

        @property
        def address(self) -> str:
            raise AttributeError("address not available in this context")

    class _BrokenAssoc:
        requestor = _BrokenRequestor()

    class _BrokenEvent:
        assoc = _BrokenAssoc()

    return _BrokenEvent()


class TestHandleAssociationRequest:
    """handle_association_request() enforces security policy via RuntimeError."""

    def test_allowed_ae_title_does_not_raise(self) -> None:
        """Whitelisted AE title + within limits → no exception."""
        sec = DicomAssociationSecurity(ae_whitelist=["CT_SCANNER_*"])
        event = _make_event(ae_title="CT_SCANNER_1", ip="10.0.0.1")
        # Should not raise
        sec.handle_association_request(event)  # type: ignore[arg-type]

    def test_handle_association_request_ae_rejected(self) -> None:
        """AE title not in whitelist → RuntimeError (pynetdicom treats this as abort)."""
        sec = DicomAssociationSecurity(ae_whitelist=["ALLOWED_AE"])
        event = _make_event(ae_title="UNKNOWN_AE", ip="10.0.0.1")

        with pytest.raises(RuntimeError, match="Association rejected"):
            sec.handle_association_request(event)  # type: ignore[arg-type]

    def test_handle_association_request_rate_limited(self) -> None:
        """IP exceeding rate limit → RuntimeError."""
        sec = DicomAssociationSecurity(ae_whitelist=None, rate_limit_per_minute=2)
        event = _make_event(ae_title="CT_SCANNER", ip="10.0.0.1")

        sec.handle_association_request(event)  # type: ignore[arg-type]  # ok
        sec.release_connection("10.0.0.1")
        sec.handle_association_request(event)  # type: ignore[arg-type]  # ok
        sec.release_connection("10.0.0.1")

        # 3rd request exceeds rate limit
        with pytest.raises(RuntimeError, match="Association rejected"):
            sec.handle_association_request(event)  # type: ignore[arg-type]

    def test_handle_association_request_connection_limited(self) -> None:
        """IP at max connections → RuntimeError."""
        sec = DicomAssociationSecurity(ae_whitelist=None, max_connections_per_ip=1)
        event = _make_event(ae_title="CT_SCANNER", ip="10.0.0.2")

        # Acquire the single allowed slot
        sec.acquire_connection("10.0.0.2")

        # Now the handler sees the connection limit exceeded
        with pytest.raises(RuntimeError, match="Association rejected"):
            sec.handle_association_request(event)  # type: ignore[arg-type]

    def test_handle_association_request_extraction_failure_rejects(self) -> None:
        """CRITICAL-3 regression: AE/IP extraction failure → RuntimeError (not silent pass).

        Before FIX-3, an extraction exception would be caught with `except: pass`,
        silently allowing the association. Now it must raise RuntimeError to force
        pynetdicom to abort the association.
        """
        sec = DicomAssociationSecurity(ae_whitelist=None)
        broken_event = _make_broken_event()

        with pytest.raises(RuntimeError, match="[Ff]ailed to extract"):
            sec.handle_association_request(broken_event)  # type: ignore[arg-type]


class TestHandleAssociationReleasedAndAborted:
    """Released/aborted handlers free connection slots gracefully."""

    def test_released_frees_connection_slot(self) -> None:
        """handle_association_released decrements the connection count."""
        sec = DicomAssociationSecurity()
        sec.acquire_connection("10.0.0.1")
        assert sec.active_connections.get("10.0.0.1", 0) == 1

        event = _make_event(ae_title="CT_SCANNER", ip="10.0.0.1")
        sec.handle_association_released(event)  # type: ignore[arg-type]

        assert sec.active_connections.get("10.0.0.1", 0) == 0

    def test_aborted_frees_connection_slot(self) -> None:
        """handle_association_aborted decrements the connection count."""
        sec = DicomAssociationSecurity()
        sec.acquire_connection("10.0.0.1")

        event = _make_event(ae_title="CT_SCANNER", ip="10.0.0.1")
        sec.handle_association_aborted(event)  # type: ignore[arg-type]

        assert sec.active_connections.get("10.0.0.1", 0) == 0


# ---------------------------------------------------------------------------
# GAP-I7: handle_association_released/aborted error paths when IP extraction fails
# ---------------------------------------------------------------------------


def _make_broken_release_event() -> object:
    """Build an event where requestor.address raises AttributeError."""

    class _BrokenRequestor:
        @property
        def address(self) -> str:
            raise AttributeError("address not available")

        @property
        def ae_title(self) -> str:
            raise AttributeError("ae_title not available")

    class _BrokenAssoc:
        requestor = _BrokenRequestor()

    class _BrokenEvent:
        assoc = _BrokenAssoc()

    return _BrokenEvent()


def _make_capturing_logger() -> tuple[object, list[tuple]]:
    """Return a (logger_shim, error_calls_list) pair for testing structlog output."""
    error_calls: list[tuple] = []

    class _CapturingLogger:
        def error(self, *args: object, **kwargs: object) -> None:
            error_calls.append(args)

        def info(self, *args: object, **kwargs: object) -> None:
            pass

        def warning(self, *args: object, **kwargs: object) -> None:
            pass

        def debug(self, *args: object, **kwargs: object) -> None:
            pass

    return _CapturingLogger(), error_calls


class TestHandleReleaseAbortedErrorPaths:
    """GAP-I7: connection_slot_leaked is logged when IP extraction fails.

    When handle_association_released or handle_association_aborted cannot
    extract the IP from the event, the connection slot cannot be freed.
    The handler must call logger.error with 'dicom.security.connection_slot_leaked'
    so operators are alerted. Verified by patching the module-level structlog logger.
    """

    def test_released_with_broken_event_logs_slot_leaked(self) -> None:
        """handle_association_released with broken event logs connection_slot_leaked."""
        import sautiris.integrations.dicom.security as _sec_mod

        sec = DicomAssociationSecurity()
        sec.acquire_connection("10.0.0.10")

        broken_event = _make_broken_release_event()
        capturing_logger, error_calls = _make_capturing_logger()
        original_logger = _sec_mod.logger
        _sec_mod.logger = capturing_logger  # type: ignore[assignment]
        try:
            sec.handle_association_released(broken_event)  # type: ignore[arg-type]
        finally:
            _sec_mod.logger = original_logger

        # Slot was NOT freed (IP was not extractable)
        assert sec.active_connections.get("10.0.0.10", 0) == 1

        event_keys = [args[0] for args in error_calls if args]
        assert any("connection_slot_leaked" in str(k) for k in event_keys), (
            f"Expected 'connection_slot_leaked' error. Got event keys: {event_keys}"
        )

    def test_aborted_with_broken_event_logs_slot_leaked(self) -> None:
        """handle_association_aborted with broken event logs connection_slot_leaked."""
        import sautiris.integrations.dicom.security as _sec_mod

        sec = DicomAssociationSecurity()
        sec.acquire_connection("10.0.0.11")

        broken_event = _make_broken_release_event()
        capturing_logger, error_calls = _make_capturing_logger()
        original_logger = _sec_mod.logger
        _sec_mod.logger = capturing_logger  # type: ignore[assignment]
        try:
            sec.handle_association_aborted(broken_event)  # type: ignore[arg-type]
        finally:
            _sec_mod.logger = original_logger

        # Slot not freed
        assert sec.active_connections.get("10.0.0.11", 0) == 1

        event_keys = [args[0] for args in error_calls if args]
        assert any("connection_slot_leaked" in str(k) for k in event_keys), (
            f"Expected 'connection_slot_leaked' error. Got event keys: {event_keys}"
        )

    def test_released_with_valid_event_does_not_log_slot_leaked(self) -> None:
        """Valid release event must NOT log connection_slot_leaked."""
        import sautiris.integrations.dicom.security as _sec_mod

        sec = DicomAssociationSecurity()
        sec.acquire_connection("10.0.0.12")
        event = _make_event(ae_title="CT_SCANNER", ip="10.0.0.12")

        capturing_logger, error_calls = _make_capturing_logger()
        original_logger = _sec_mod.logger
        _sec_mod.logger = capturing_logger  # type: ignore[assignment]
        try:
            sec.handle_association_released(event)  # type: ignore[arg-type]
        finally:
            _sec_mod.logger = original_logger

        # Slot freed successfully
        assert sec.active_connections.get("10.0.0.12", 0) == 0

        event_keys = [args[0] for args in error_calls if args]
        assert not any("connection_slot_leaked" in str(k) for k in event_keys), (
            f"No slot_leaked log expected on a successful release. Got: {event_keys}"
        )
