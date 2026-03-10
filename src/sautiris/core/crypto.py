"""Transparent field-level encryption using Fernet (AES-128-CBC + HMAC-SHA256).

The ``EncryptedString`` SQLAlchemy TypeDecorator reads the encryption key from
the ``SAUTIRIS_ENCRYPTION_KEY`` environment variable at query time.  When the
variable is unset (development), values are stored and retrieved as plaintext.

Key generation:
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())   # store as SAUTIRIS_ENCRYPTION_KEY
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from cryptography.fernet import InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

logger = structlog.get_logger(__name__)


class DecryptionError(Exception):
    """Raised when Fernet decryption fails on a value that appears to be encrypted."""


def _fernet_encrypt(value: str, key_str: str) -> str:
    """Encrypt *value* using Fernet with the given base64-encoded key."""
    from cryptography.fernet import Fernet  # local import — optional dep

    return Fernet(key_str.encode()).encrypt(value.encode()).decode()


def _fernet_decrypt(value: str, key_str: str) -> str:
    """Decrypt a Fernet-encrypted string. Raises ``InvalidToken`` on failure."""
    from cryptography.fernet import Fernet  # local import — optional dep

    return Fernet(key_str.encode()).decrypt(value.encode()).decode()


class EncryptedString(TypeDecorator[str]):
    """Column type that transparently encrypts/decrypts string values via Fernet.

    When ``SAUTIRIS_ENCRYPTION_KEY`` is unset the column behaves like a plain
    ``String`` — no encryption, no errors.  Startup validation in ``app.py``
    enforces that the key *is* set in production.

    Attributes:
        impl: Underlying SA column type (String).
        cache_ok: Safe for query caching — key is read at bind/result time.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        key = os.environ.get("SAUTIRIS_ENCRYPTION_KEY", "")
        if not key:
            logger.critical(
                "crypto.storing_unencrypted",
                msg="SAUTIRIS_ENCRYPTION_KEY not set — storing value as plaintext",
            )
            return value
        return _fernet_encrypt(value, key)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        key = os.environ.get("SAUTIRIS_ENCRYPTION_KEY", "")
        if not key:
            return value
        try:
            return _fernet_decrypt(value, key)
        except InvalidToken:
            if value.startswith("gAAAAA"):
                # Value is a Fernet token — decryption failed (wrong key or data corruption).
                # Returning ciphertext as plaintext would silently corrupt data; raise instead.
                logger.critical(
                    "crypto.decrypt_failed",
                    msg=(
                        "Fernet decryption failed — value appears encrypted but "
                        "could not be decrypted (wrong key or corrupted data)"
                    ),
                )
                raise DecryptionError(
                    "Fernet decryption failed — value appears encrypted but could not be decrypted"
                ) from None
            # Value does not look like a Fernet token — treat as pre-encryption legacy plaintext.
            # Log at CRITICAL so operators know unencrypted values exist in the database.
            logger.critical(
                "crypto.decrypt_failed_legacy",
                msg=(
                    "Fernet decryption failed — treating as pre-encryption legacy plaintext; "
                    "re-encrypt this value at next write"
                ),
            )
            return value
