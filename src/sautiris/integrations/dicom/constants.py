"""Shared DICOM constants and utilities for all SCP modules."""

from __future__ import annotations

import ssl
from collections.abc import Callable
from typing import Any

# SpecificCharacterSet for UTF-8 (ISO_IR 192) — all outbound datasets
CHARSET_UTF8 = "ISO_IR 192"

# Default transfer syntaxes supported by all SCPs.
# #39: immutable tuple to prevent accidental mutation.
DEFAULT_TRANSFER_SYNTAXES: tuple[str, ...] = (
    "1.2.840.10008.1.2.1",    # Explicit VR Little Endian
    "1.2.840.10008.1.2",      # Implicit VR Little Endian
    "1.2.840.10008.1.2.4.50", # JPEG Baseline (Process 1)
    "1.2.840.10008.1.2.4.70", # JPEG Lossless (Process 14 SV1)
    "1.2.840.10008.1.2.4.90", # JPEG 2000 Lossless Only
    "1.2.840.10008.1.2.4.91", # JPEG 2000
    "1.2.840.10008.1.2.5",    # RLE Lossless
    "1.2.840.10008.1.2.1.99", # Deflated Explicit VR Little Endian
)

# ---------------------------------------------------------------------------
# Type aliases for DICOM event handler lists — #52
# ---------------------------------------------------------------------------
# pynetdicom event types are NamedTuple subclasses (InterventionEvent /
# NotificationEvent) with no shared public base type exported from the library.
# We use Any for the event-type slot so that both variants are accepted without
# requiring per-site `type: ignore` annotations.

#: A single DICOM event handler entry: (event_type, handler_callable).
#: The event_type is a pynetdicom InterventionEvent or NotificationEvent.
DicomEventHandler = tuple[Any, Callable[..., Any]]

#: A list of DICOM event handler entries passed to pynetdicom start_server.
DicomHandlerList = list[DicomEventHandler]


def build_dicom_ssl_context(
    tls_cert: str | None = None,
    tls_key: str | None = None,
    tls_ca_cert: str | None = None,
) -> ssl.SSLContext | None:
    """Build an SSL context for DICOM TLS from cert/key/CA parameters.

    Returns None if TLS is not configured (no cert+key provided).

    Args:
        tls_cert: Path to TLS certificate file.
        tls_key: Path to TLS private key file.
        tls_ca_cert: Path to CA certificate file for mutual TLS (client verification).

    Notes:
        #22: Enforces TLSv1.2 minimum and restricts cipher suites to
        ECDHE/DHE + AESGCM/CHACHA20 combinations, explicitly excluding
        NULL, MD5, DSS, RC4, and 3DES ciphers.
        #47: Parameters default to None instead of empty string sentinel.
    """
    if not (tls_cert and tls_key):
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # #22 — restrict to strong cipher suites only; disallow weak/deprecated ciphers
    ctx.set_ciphers(
        "ECDHE+AESGCM:DHE+AESGCM:ECDHE+CHACHA20:DHE+CHACHA20:!aNULL:!MD5:!DSS:!RC4:!3DES"
    )
    ctx.load_cert_chain(certfile=tls_cert, keyfile=tls_key)
    if tls_ca_cert:
        ctx.load_verify_locations(cafile=tls_ca_cert)
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx
