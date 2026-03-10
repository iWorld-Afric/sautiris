"""Shared DICOM constants and utilities for all SCP modules."""

from __future__ import annotations

import ssl

# SpecificCharacterSet for UTF-8 (ISO_IR 192) — all outbound datasets
CHARSET_UTF8 = "ISO_IR 192"

# Default transfer syntaxes supported by all SCPs
DEFAULT_TRANSFER_SYNTAXES: list[str] = [
    "1.2.840.10008.1.2.1",  # Explicit VR Little Endian
    "1.2.840.10008.1.2",  # Implicit VR Little Endian
    "1.2.840.10008.1.2.4.50",  # JPEG Baseline (Process 1)
    "1.2.840.10008.1.2.4.70",  # JPEG Lossless (Process 14 SV1)
    "1.2.840.10008.1.2.4.90",  # JPEG 2000 Lossless Only
    "1.2.840.10008.1.2.4.91",  # JPEG 2000
    "1.2.840.10008.1.2.5",  # RLE Lossless
    "1.2.840.10008.1.2.1.99",  # Deflated Explicit VR Little Endian
]


def build_dicom_ssl_context(
    tls_cert: str,
    tls_key: str,
    tls_ca_cert: str = "",
) -> ssl.SSLContext | None:
    """Build an SSL context for DICOM TLS from cert/key/CA parameters.

    Returns None if TLS is not configured (no cert+key provided).

    Args:
        tls_cert: Path to TLS certificate file.
        tls_key: Path to TLS private key file.
        tls_ca_cert: Path to CA certificate file for mutual TLS (client verification).
    """
    if not (tls_cert and tls_key):
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=tls_cert, keyfile=tls_key)
    if tls_ca_cert:
        ctx.load_verify_locations(cafile=tls_ca_cert)
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx
