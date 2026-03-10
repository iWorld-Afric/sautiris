"""Shared DICOM constants for all SCP modules."""

from __future__ import annotations

# SpecificCharacterSet for UTF-8 (ISO_IR 192) — all outbound datasets
CHARSET_UTF8 = "ISO_IR 192"

# Default transfer syntaxes supported by all SCPs
DEFAULT_TRANSFER_SYNTAXES: list[str] = [
    "1.2.840.10008.1.2.1",    # Explicit VR Little Endian
    "1.2.840.10008.1.2",      # Implicit VR Little Endian
    "1.2.840.10008.1.2.4.50", # JPEG Baseline (Process 1)
    "1.2.840.10008.1.2.4.70", # JPEG Lossless (Process 14 SV1)
    "1.2.840.10008.1.2.4.90", # JPEG 2000 Lossless Only
    "1.2.840.10008.1.2.4.91", # JPEG 2000
    "1.2.840.10008.1.2.5",    # RLE Lossless
    "1.2.840.10008.1.2.1.99", # Deflated Explicit VR Little Endian
]
