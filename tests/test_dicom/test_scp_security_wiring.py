"""Tests for DicomAssociationSecurity wiring in all 3 DICOM SCPs.

Issue #6: Verifies that StoreSCPServer, MWLServer, and MPPSServer correctly
register EVT_REQUESTED/EVT_RELEASED/EVT_ABORTED handlers when a security
instance is provided, and that they skip security handlers when security is None
(backward compatibility). Also tests TLS context creation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from pynetdicom import evt

from sautiris.integrations.dicom.mpps_scp import MPPSServer
from sautiris.integrations.dicom.mwl_scp import MWLServer
from sautiris.integrations.dicom.security import DicomAssociationSecurity
from sautiris.integrations.dicom.store_scp import StoreSCPServer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_handler_events(mock_ae: MagicMock) -> list[Any]:
    """Extract the event types from the evt_handlers kwarg of start_server."""
    mock_ae.start_server.assert_called_once()
    kwargs = mock_ae.start_server.call_args.kwargs
    handlers = kwargs.get("evt_handlers", [])
    return [h[0] for h in handlers]


def _extract_handler_map(mock_ae: MagicMock) -> dict[Any, Any]:
    """Extract a mapping of event type -> handler callable."""
    kwargs = mock_ae.start_server.call_args.kwargs
    handlers = kwargs.get("evt_handlers", [])
    return {h[0]: h[1] for h in handlers}


def _start_with_mock_ae(server: Any, module_path: str) -> MagicMock:
    """Start a server with a mocked AE class and return the mock AE instance."""
    mock_ae_instance = MagicMock()
    with patch(module_path, return_value=mock_ae_instance):
        server.start()
    return mock_ae_instance


# ---------------------------------------------------------------------------
# StoreSCPServer security wiring
# ---------------------------------------------------------------------------


class TestStoreSCPSecurityWiring:
    """StoreSCPServer registers security handlers when security is provided."""

    def test_no_security_no_security_handlers(self) -> None:
        """When security=None, only EVT_C_STORE is registered (backward compat)."""
        server = StoreSCPServer(security=None)
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.store_scp.AE")
        events = _extract_handler_events(mock_ae)
        assert evt.EVT_C_STORE in events
        assert evt.EVT_REQUESTED not in events
        assert evt.EVT_RELEASED not in events
        assert evt.EVT_ABORTED not in events

    def test_with_security_registers_all_handlers(self) -> None:
        """When security is provided, EVT_REQUESTED/RELEASED/ABORTED are added."""
        security = DicomAssociationSecurity()
        server = StoreSCPServer(security=security)
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.store_scp.AE")
        events = _extract_handler_events(mock_ae)
        assert evt.EVT_C_STORE in events
        assert evt.EVT_REQUESTED in events
        assert evt.EVT_RELEASED in events
        assert evt.EVT_ABORTED in events

    def test_security_handlers_point_to_security_methods(self) -> None:
        """The handler callables must be the security instance methods."""
        security = DicomAssociationSecurity()
        server = StoreSCPServer(security=security)
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.store_scp.AE")
        handler_map = _extract_handler_map(mock_ae)
        assert handler_map[evt.EVT_REQUESTED] == security.handle_association_request
        assert handler_map[evt.EVT_RELEASED] == security.handle_association_released
        assert handler_map[evt.EVT_ABORTED] == security.handle_association_aborted

    def test_security_stored_as_attribute(self) -> None:
        """The security parameter is stored as self._security."""
        security = DicomAssociationSecurity()
        server = StoreSCPServer(security=security)
        assert server._security is security

    def test_security_default_is_none(self) -> None:
        """Default value for security is None."""
        server = StoreSCPServer()
        assert server._security is None


# ---------------------------------------------------------------------------
# MWLServer security wiring
# ---------------------------------------------------------------------------


class TestMWLServerSecurityWiring:
    """MWLServer registers security handlers when security is provided."""

    def test_no_security_no_security_handlers(self) -> None:
        """When security=None, only EVT_C_FIND is registered."""
        server = MWLServer(security=None)
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mwl_scp.AE")
        events = _extract_handler_events(mock_ae)
        assert evt.EVT_C_FIND in events
        assert evt.EVT_REQUESTED not in events
        assert evt.EVT_RELEASED not in events
        assert evt.EVT_ABORTED not in events

    def test_with_security_registers_all_handlers(self) -> None:
        """When security is provided, EVT_REQUESTED/RELEASED/ABORTED are added."""
        security = DicomAssociationSecurity()
        server = MWLServer(security=security)
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mwl_scp.AE")
        events = _extract_handler_events(mock_ae)
        assert evt.EVT_C_FIND in events
        assert evt.EVT_REQUESTED in events
        assert evt.EVT_RELEASED in events
        assert evt.EVT_ABORTED in events

    def test_security_handlers_point_to_security_methods(self) -> None:
        """The handler callables must be the security instance methods."""
        security = DicomAssociationSecurity()
        server = MWLServer(security=security)
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mwl_scp.AE")
        handler_map = _extract_handler_map(mock_ae)
        assert handler_map[evt.EVT_REQUESTED] == security.handle_association_request
        assert handler_map[evt.EVT_RELEASED] == security.handle_association_released
        assert handler_map[evt.EVT_ABORTED] == security.handle_association_aborted

    def test_security_stored_as_attribute(self) -> None:
        """The security parameter is stored as self._security."""
        security = DicomAssociationSecurity()
        server = MWLServer(security=security)
        assert server._security is security

    def test_security_default_is_none(self) -> None:
        """Default value for security is None."""
        server = MWLServer()
        assert server._security is None


# ---------------------------------------------------------------------------
# MPPSServer security wiring
# ---------------------------------------------------------------------------


class TestMPPSServerSecurityWiring:
    """MPPSServer registers security handlers when security is provided."""

    def test_no_security_no_security_handlers(self) -> None:
        """When security=None, only EVT_N_CREATE and EVT_N_SET are registered."""
        server = MPPSServer(security=None)
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mpps_scp.AE")
        events = _extract_handler_events(mock_ae)
        assert evt.EVT_N_CREATE in events
        assert evt.EVT_N_SET in events
        assert evt.EVT_REQUESTED not in events
        assert evt.EVT_RELEASED not in events
        assert evt.EVT_ABORTED not in events

    def test_with_security_registers_all_handlers(self) -> None:
        """When security is provided, EVT_REQUESTED/RELEASED/ABORTED are added."""
        security = DicomAssociationSecurity()
        server = MPPSServer(security=security)
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mpps_scp.AE")
        events = _extract_handler_events(mock_ae)
        assert evt.EVT_N_CREATE in events
        assert evt.EVT_N_SET in events
        assert evt.EVT_REQUESTED in events
        assert evt.EVT_RELEASED in events
        assert evt.EVT_ABORTED in events

    def test_security_handlers_point_to_security_methods(self) -> None:
        """The handler callables must be the security instance methods."""
        security = DicomAssociationSecurity()
        server = MPPSServer(security=security)
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mpps_scp.AE")
        handler_map = _extract_handler_map(mock_ae)
        assert handler_map[evt.EVT_REQUESTED] == security.handle_association_request
        assert handler_map[evt.EVT_RELEASED] == security.handle_association_released
        assert handler_map[evt.EVT_ABORTED] == security.handle_association_aborted

    def test_security_stored_as_attribute(self) -> None:
        """The security parameter is stored as self._security."""
        security = DicomAssociationSecurity()
        server = MPPSServer(security=security)
        assert server._security is security

    def test_security_default_is_none(self) -> None:
        """Default value for security is None."""
        server = MPPSServer()
        assert server._security is None


# ---------------------------------------------------------------------------
# TLS context creation
# ---------------------------------------------------------------------------


class TestTLSContextCreation:
    """_build_ssl_context creates SSLContext when cert+key are provided."""

    def test_no_tls_returns_none_store(self) -> None:
        """StoreSCPServer with no TLS params returns None from _build_ssl_context."""
        server = StoreSCPServer()
        assert server._build_ssl_context() is None

    def test_no_tls_returns_none_mwl(self) -> None:
        """MWLServer with no TLS params returns None from _build_ssl_context."""
        server = MWLServer()
        assert server._build_ssl_context() is None

    def test_no_tls_returns_none_mpps(self) -> None:
        """MPPSServer with no TLS params returns None from _build_ssl_context."""
        server = MPPSServer()
        assert server._build_ssl_context() is None

    def test_empty_strings_returns_none(self) -> None:
        """Empty cert/key strings return None (TLS not configured)."""
        server = StoreSCPServer(tls_cert="", tls_key="")
        assert server._build_ssl_context() is None

    def test_cert_only_returns_none(self) -> None:
        """Cert without key returns None (both required)."""
        server = StoreSCPServer(tls_cert="/path/to/cert.pem", tls_key="")
        assert server._build_ssl_context() is None

    def test_key_only_returns_none(self) -> None:
        """Key without cert returns None (both required)."""
        server = StoreSCPServer(tls_cert="", tls_key="/path/to/key.pem")
        assert server._build_ssl_context() is None

    def test_cert_and_key_creates_ssl_context(self) -> None:
        """When cert+key are provided, _build_ssl_context creates an SSLContext."""
        import ssl

        real_ssl_ctx_class = ssl.SSLContext
        server = StoreSCPServer(
            tls_cert="/path/to/cert.pem",
            tls_key="/path/to/key.pem",
        )
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock(spec=real_ssl_ctx_class)
            mock_ctx_class.return_value = mock_ctx

            result = server._build_ssl_context()

            mock_ctx_class.assert_called_once_with(ssl.PROTOCOL_TLS_SERVER)
            mock_ctx.load_cert_chain.assert_called_once_with(
                certfile="/path/to/cert.pem",
                keyfile="/path/to/key.pem",
            )
            # HIPAA: TLS 1.2 minimum must be enforced
            assert mock_ctx.minimum_version == ssl.TLSVersion.TLSv1_2
            assert result is mock_ctx

    def test_ca_cert_enables_client_verification(self) -> None:
        """When tls_ca_cert is also set, load_verify_locations + CERT_REQUIRED."""
        import ssl

        real_ssl_ctx_class = ssl.SSLContext
        server = StoreSCPServer(
            tls_cert="/path/to/cert.pem",
            tls_key="/path/to/key.pem",
            tls_ca_cert="/path/to/ca.pem",
        )
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock(spec=real_ssl_ctx_class)
            mock_ctx_class.return_value = mock_ctx

            result = server._build_ssl_context()

            mock_ctx.load_verify_locations.assert_called_once_with(cafile="/path/to/ca.pem")
            assert mock_ctx.verify_mode == ssl.CERT_REQUIRED
            assert mock_ctx.minimum_version == ssl.TLSVersion.TLSv1_2
            assert result is mock_ctx

    def test_no_ca_cert_does_not_call_load_verify(self) -> None:
        """Without tls_ca_cert, load_verify_locations is not called."""
        import ssl

        real_ssl_ctx_class = ssl.SSLContext
        server = StoreSCPServer(
            tls_cert="/path/to/cert.pem",
            tls_key="/path/to/key.pem",
        )
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock(spec=real_ssl_ctx_class)
            mock_ctx_class.return_value = mock_ctx

            server._build_ssl_context()

            mock_ctx.load_verify_locations.assert_not_called()

    def test_ssl_context_passed_to_start_server(self) -> None:
        """When TLS is configured, ssl_context is passed to start_server."""
        import ssl

        server = StoreSCPServer(
            tls_cert="/path/to/cert.pem",
            tls_key="/path/to/key.pem",
        )
        mock_ssl_ctx = MagicMock(spec=ssl.SSLContext)
        with patch.object(server, "_build_ssl_context", return_value=mock_ssl_ctx):
            mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.store_scp.AE")
        kwargs = mock_ae.start_server.call_args.kwargs
        assert kwargs["ssl_context"] is mock_ssl_ctx

    def test_no_tls_passes_none_to_start_server(self) -> None:
        """When no TLS is configured, ssl_context=None is passed to start_server."""
        server = StoreSCPServer()
        mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.store_scp.AE")
        kwargs = mock_ae.start_server.call_args.kwargs
        assert kwargs["ssl_context"] is None


# ---------------------------------------------------------------------------
# GAP-1: TLS _build_ssl_context() behavioral tests for MWL and MPPS
# ---------------------------------------------------------------------------


class TestTLSContextCreationMWL:
    """_build_ssl_context behavioral tests for MWLServer (GAP-1)."""

    def test_cert_and_key_creates_ssl_context(self) -> None:
        """MWLServer: cert+key creates SSLContext with TLS 1.2 minimum."""
        import ssl

        real_ssl_ctx_class = ssl.SSLContext
        server = MWLServer(tls_cert="/path/to/cert.pem", tls_key="/path/to/key.pem")
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock(spec=real_ssl_ctx_class)
            mock_ctx_class.return_value = mock_ctx
            result = server._build_ssl_context()
            mock_ctx_class.assert_called_once_with(ssl.PROTOCOL_TLS_SERVER)
            mock_ctx.load_cert_chain.assert_called_once_with(
                certfile="/path/to/cert.pem", keyfile="/path/to/key.pem"
            )
            assert mock_ctx.minimum_version == ssl.TLSVersion.TLSv1_2
            assert result is mock_ctx

    def test_ca_cert_enables_client_verification(self) -> None:
        """MWLServer: CA cert enables mutual TLS with CERT_REQUIRED."""
        import ssl

        real_ssl_ctx_class = ssl.SSLContext
        server = MWLServer(
            tls_cert="/path/to/cert.pem",
            tls_key="/path/to/key.pem",
            tls_ca_cert="/path/to/ca.pem",
        )
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock(spec=real_ssl_ctx_class)
            mock_ctx_class.return_value = mock_ctx
            result = server._build_ssl_context()
            mock_ctx.load_verify_locations.assert_called_once_with(cafile="/path/to/ca.pem")
            assert mock_ctx.verify_mode == ssl.CERT_REQUIRED
            assert mock_ctx.minimum_version == ssl.TLSVersion.TLSv1_2
            assert result is mock_ctx

    def test_ssl_context_passed_to_start_server(self) -> None:
        """MWLServer: ssl_context kwarg reaches start_server."""
        import ssl

        server = MWLServer(tls_cert="/path/to/cert.pem", tls_key="/path/to/key.pem")
        mock_ssl_ctx = MagicMock(spec=ssl.SSLContext)
        with patch.object(server, "_build_ssl_context", return_value=mock_ssl_ctx):
            mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mwl_scp.AE")
        kwargs = mock_ae.start_server.call_args.kwargs
        assert kwargs["ssl_context"] is mock_ssl_ctx


class TestTLSContextCreationMPPS:
    """_build_ssl_context behavioral tests for MPPSServer (GAP-1)."""

    def test_cert_and_key_creates_ssl_context(self) -> None:
        """MPPSServer: cert+key creates SSLContext with TLS 1.2 minimum."""
        import ssl

        real_ssl_ctx_class = ssl.SSLContext
        server = MPPSServer(tls_cert="/path/to/cert.pem", tls_key="/path/to/key.pem")
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock(spec=real_ssl_ctx_class)
            mock_ctx_class.return_value = mock_ctx
            result = server._build_ssl_context()
            mock_ctx_class.assert_called_once_with(ssl.PROTOCOL_TLS_SERVER)
            mock_ctx.load_cert_chain.assert_called_once_with(
                certfile="/path/to/cert.pem", keyfile="/path/to/key.pem"
            )
            assert mock_ctx.minimum_version == ssl.TLSVersion.TLSv1_2
            assert result is mock_ctx

    def test_ca_cert_enables_client_verification(self) -> None:
        """MPPSServer: CA cert enables mutual TLS with CERT_REQUIRED."""
        import ssl

        real_ssl_ctx_class = ssl.SSLContext
        server = MPPSServer(
            tls_cert="/path/to/cert.pem",
            tls_key="/path/to/key.pem",
            tls_ca_cert="/path/to/ca.pem",
        )
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock(spec=real_ssl_ctx_class)
            mock_ctx_class.return_value = mock_ctx
            result = server._build_ssl_context()
            mock_ctx.load_verify_locations.assert_called_once_with(cafile="/path/to/ca.pem")
            assert mock_ctx.verify_mode == ssl.CERT_REQUIRED
            assert mock_ctx.minimum_version == ssl.TLSVersion.TLSv1_2
            assert result is mock_ctx

    def test_ssl_context_passed_to_start_server(self) -> None:
        """MPPSServer: ssl_context kwarg reaches start_server."""
        import ssl

        server = MPPSServer(tls_cert="/path/to/cert.pem", tls_key="/path/to/key.pem")
        mock_ssl_ctx = MagicMock(spec=ssl.SSLContext)
        with patch.object(server, "_build_ssl_context", return_value=mock_ssl_ctx):
            mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mpps_scp.AE")
        kwargs = mock_ae.start_server.call_args.kwargs
        assert kwargs["ssl_context"] is mock_ssl_ctx


# ---------------------------------------------------------------------------
# GAP-2: Combined TLS + security wiring test
# ---------------------------------------------------------------------------


class TestCombinedTLSAndSecurity:
    """Verify TLS and security handlers work together in start() (GAP-2)."""

    def test_store_scp_tls_plus_security(self) -> None:
        """StoreSCPServer with both security and TLS passes both to start_server."""
        import ssl

        security = DicomAssociationSecurity()
        server = StoreSCPServer(security=security, tls_cert="/cert.pem", tls_key="/key.pem")
        mock_ssl_ctx = MagicMock(spec=ssl.SSLContext)
        with patch.object(server, "_build_ssl_context", return_value=mock_ssl_ctx):
            mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.store_scp.AE")
        kwargs = mock_ae.start_server.call_args.kwargs
        assert kwargs["ssl_context"] is mock_ssl_ctx
        events = [h[0] for h in kwargs["evt_handlers"]]
        assert evt.EVT_C_STORE in events
        assert evt.EVT_REQUESTED in events
        assert evt.EVT_RELEASED in events
        assert evt.EVT_ABORTED in events

    def test_mwl_server_tls_plus_security(self) -> None:
        """MWLServer with both security and TLS passes both to start_server."""
        import ssl

        security = DicomAssociationSecurity()
        server = MWLServer(security=security, tls_cert="/cert.pem", tls_key="/key.pem")
        mock_ssl_ctx = MagicMock(spec=ssl.SSLContext)
        with patch.object(server, "_build_ssl_context", return_value=mock_ssl_ctx):
            mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mwl_scp.AE")
        kwargs = mock_ae.start_server.call_args.kwargs
        assert kwargs["ssl_context"] is mock_ssl_ctx
        events = [h[0] for h in kwargs["evt_handlers"]]
        assert evt.EVT_C_FIND in events
        assert evt.EVT_REQUESTED in events
        assert evt.EVT_RELEASED in events
        assert evt.EVT_ABORTED in events

    def test_mpps_server_tls_plus_security(self) -> None:
        """MPPSServer with both security and TLS passes both to start_server."""
        import ssl

        security = DicomAssociationSecurity()
        server = MPPSServer(security=security, tls_cert="/cert.pem", tls_key="/key.pem")
        mock_ssl_ctx = MagicMock(spec=ssl.SSLContext)
        with patch.object(server, "_build_ssl_context", return_value=mock_ssl_ctx):
            mock_ae = _start_with_mock_ae(server, "sautiris.integrations.dicom.mpps_scp.AE")
        kwargs = mock_ae.start_server.call_args.kwargs
        assert kwargs["ssl_context"] is mock_ssl_ctx
        events = [h[0] for h in kwargs["evt_handlers"]]
        assert evt.EVT_N_CREATE in events
        assert evt.EVT_N_SET in events
        assert evt.EVT_REQUESTED in events
        assert evt.EVT_RELEASED in events
        assert evt.EVT_ABORTED in events


# ---------------------------------------------------------------------------
# TLS params stored correctly
# ---------------------------------------------------------------------------


class TestTLSParamsStored:
    """TLS parameters are stored as instance attributes."""

    def test_store_scp_tls_defaults(self) -> None:
        server = StoreSCPServer()
        assert server._tls_cert == ""
        assert server._tls_key == ""
        assert server._tls_ca_cert == ""

    def test_mwl_server_tls_defaults(self) -> None:
        server = MWLServer()
        assert server._tls_cert == ""
        assert server._tls_key == ""
        assert server._tls_ca_cert == ""

    def test_mpps_server_tls_defaults(self) -> None:
        server = MPPSServer()
        assert server._tls_cert == ""
        assert server._tls_key == ""
        assert server._tls_ca_cert == ""

    def test_store_scp_tls_custom(self) -> None:
        server = StoreSCPServer(
            tls_cert="/cert.pem",
            tls_key="/key.pem",
            tls_ca_cert="/ca.pem",
        )
        assert server._tls_cert == "/cert.pem"
        assert server._tls_key == "/key.pem"
        assert server._tls_ca_cert == "/ca.pem"

    def test_mwl_server_tls_custom(self) -> None:
        server = MWLServer(
            tls_cert="/cert.pem",
            tls_key="/key.pem",
            tls_ca_cert="/ca.pem",
        )
        assert server._tls_cert == "/cert.pem"
        assert server._tls_key == "/key.pem"
        assert server._tls_ca_cert == "/ca.pem"

    def test_mpps_server_tls_custom(self) -> None:
        server = MPPSServer(
            tls_cert="/cert.pem",
            tls_key="/key.pem",
            tls_ca_cert="/ca.pem",
        )
        assert server._tls_cert == "/cert.pem"
        assert server._tls_key == "/key.pem"
        assert server._tls_ca_cert == "/ca.pem"
