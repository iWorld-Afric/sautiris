"""SautiRIS — Open-source Radiology Information System."""

__version__ = "1.0.0a1"

from sautiris.app import create_ris_app
from sautiris.config import SautiRISSettings

__all__ = ["__version__", "create_ris_app", "SautiRISSettings"]
