"""Abstract base class for all SautiRIS DICOM SCP servers.

Extracts common startup/shutdown patterns shared by MWLServer,
StoreSCPServer, and MPPSServer so they don't duplicate boilerplate
(#30: BaseSCPServer refactor).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import structlog
from pynetdicom import AE as _AE
from pynetdicom import evt

from sautiris.integrations.dicom.constants import (
    DEFAULT_TRANSFER_SYNTAXES,
    DicomHandlerList,
    build_dicom_ssl_context,
)

if TYPE_CHECKING:
    import ssl

    from sautiris.integrations.dicom.security import DicomAssociationSecurity

logger = structlog.get_logger(__name__)


class BaseSCPServer(ABC):
    """Abstract base for all SautiRIS DICOM SCP servers.

    Handles the common lifecycle (start / stop) and delegates SOP class +
    handler registration to concrete subclasses via
    :meth:`_get_sop_classes_and_handlers`.

    Subclasses **must** implement :meth:`_get_sop_classes_and_handlers` and
    **may** override :meth:`_log_started` to emit a server-specific startup
    log message.

    Args:
        ae_title: Application Entity title for this SCP.
        port: TCP port to listen on.
        loop: The asyncio event loop used to dispatch async callbacks.
        bind_address: IP address to bind to.  Defaults to ``"127.0.0.1"``
            (localhost-only).
        security: Optional :class:`DicomAssociationSecurity` instance that
            enforces AE whitelist, connection limits, and rate limiting.
        tls_cert: Path to TLS certificate file.  Empty string or ``None``
            disables TLS.
        tls_key: Path to TLS private key file.  Empty string or ``None``
            disables TLS.
        tls_ca_cert: Path to CA certificate for mutual TLS.  Empty string
            or ``None`` disables client verification.
    """

    def __init__(
        self,
        ae_title: str,
        port: int,
        loop: asyncio.AbstractEventLoop | None = None,
        bind_address: str = "127.0.0.1",
        security: DicomAssociationSecurity | None = None,
        tls_cert: str = "",
        tls_key: str = "",
        tls_ca_cert: str = "",
    ) -> None:
        self.ae_title = ae_title
        self.port = port
        self._loop = loop
        self._bind_address = bind_address
        self._security = security
        self._tls_cert = tls_cert
        self._tls_key = tls_key
        self._tls_ca_cert = tls_ca_cert
        self._ae: _AE | None = None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def _get_sop_classes_and_handlers(self) -> tuple[list[str], DicomHandlerList]:
        """Return the SOP class UIDs and event handlers for this SCP.

        Returns:
            A 2-tuple of:
            - ``sop_class_uids``: list of SOP Class UIDs to register.
            - ``handlers``: list of ``(evt_type, handler_fn)`` tuples that
              are specific to this SCP (e.g. EVT_C_FIND for MWL).
              The base class appends security handlers automatically.
        """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        """Build an SSL context from TLS cert/key/CA parameters."""
        return build_dicom_ssl_context(self._tls_cert, self._tls_key, self._tls_ca_cert)

    def _build_handler_list(self, handlers: DicomHandlerList) -> DicomHandlerList:
        """Append security handlers if a security policy is configured.

        Args:
            handlers: The SCP-specific handlers (e.g. EVT_C_FIND).

        Returns:
            New list including EVT_REQUESTED / EVT_RELEASED / EVT_ABORTED
            from the security instance when one is provided.
        """
        result = list(handlers)
        if self._security:
            result.extend(
                [
                    (evt.EVT_REQUESTED, self._security.handle_association_request),
                    (evt.EVT_RELEASED, self._security.handle_association_released),
                    (evt.EVT_ABORTED, self._security.handle_association_aborted),
                ]
            )
        return result

    def _log_started(self, tls_enabled: bool) -> None:
        """Log that the SCP has started.  Subclasses may override for extra fields."""
        logger.info(
            "scp.server_started",
            ae_title=self.ae_title,
            port=self.port,
            tls_enabled=tls_enabled,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _make_ae(self) -> _AE:
        """Create the pynetdicom AE instance.

        Subclasses import ``AE`` into their own module namespace so that
        ``patch("sautiris.integrations.dicom.<scp_module>.AE")`` works in
        tests.  This factory method is overridden by each subclass to call
        *their* ``AE`` reference, making patch() target the correct module.
        """
        return _AE(ae_title=self.ae_title)

    def start(self) -> None:
        """Start the SCP in non-blocking mode.

        Registers SOP classes, wires event handlers (including optional
        security handlers), applies TLS if configured, and starts the
        pynetdicom AE server.
        """
        self._ae = self._make_ae()

        sop_class_uids, scp_handlers = self._get_sop_classes_and_handlers()

        for sop_class in sop_class_uids:
            self._ae.add_supported_context(sop_class, DEFAULT_TRANSFER_SYNTAXES)

        handlers = self._build_handler_list(scp_handlers)

        ssl_context = self._build_ssl_context()
        if ssl_context is None:
            logger.warning(
                "scp.tls_disabled",
                ae_title=self.ae_title,
                port=self.port,
                msg="SCP starting without TLS — DICOM traffic is unencrypted",
            )

        self._ae.start_server(
            (self._bind_address, self.port),
            block=False,
            ssl_context=ssl_context,
            evt_handlers=handlers,  # type: ignore[arg-type]
        )
        self._log_started(tls_enabled=ssl_context is not None)

    def stop(self) -> None:
        """Stop the SCP gracefully by shutting down the AE."""
        if self._ae:
            self._ae.shutdown()
            self._ae = None
            logger.info("scp.server_stopped", ae_title=self.ae_title)
