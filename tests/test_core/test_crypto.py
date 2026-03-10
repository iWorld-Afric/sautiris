"""Tests for EncryptedString TypeDecorator (issue #6)."""

from __future__ import annotations

import pytest

from sautiris.core.crypto import DecryptionError, EncryptedString


class TestEncryptedString:
    """Round-trip encryption and graceful fallback when key is unset."""

    @pytest.fixture
    def fernet_key(self) -> str:
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode()

    def test_encrypt_decrypt_round_trip(
        self, fernet_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAUTIRIS_ENCRYPTION_KEY", fernet_key)
        enc = EncryptedString()
        plaintext = "supersecret_password"
        encrypted = enc.process_bind_param(plaintext, None)
        assert encrypted != plaintext
        assert encrypted is not None
        decrypted = enc.process_result_value(encrypted, None)
        assert decrypted == plaintext

    def test_none_passthrough(self, fernet_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAUTIRIS_ENCRYPTION_KEY", fernet_key)
        enc = EncryptedString()
        assert enc.process_bind_param(None, None) is None
        assert enc.process_result_value(None, None) is None

    def test_no_key_stores_plaintext(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAUTIRIS_ENCRYPTION_KEY", raising=False)
        enc = EncryptedString()
        plaintext = "devpassword"
        result = enc.process_bind_param(plaintext, None)
        assert result == plaintext

    def test_no_key_returns_plaintext_on_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAUTIRIS_ENCRYPTION_KEY", raising=False)
        enc = EncryptedString()
        assert enc.process_result_value("devpassword", None) == "devpassword"

    def test_legacy_plaintext_fallback_on_decrypt(
        self, fernet_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rows stored before encryption was enabled should be returned as-is."""
        monkeypatch.setenv("SAUTIRIS_ENCRYPTION_KEY", fernet_key)
        enc = EncryptedString()
        # "plaintext" is not a valid Fernet token — should be returned as-is
        result = enc.process_result_value("oldplaintext", None)
        assert result == "oldplaintext"

    def test_different_keys_cannot_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cryptography.fernet import Fernet

        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()

        monkeypatch.setenv("SAUTIRIS_ENCRYPTION_KEY", key1)
        enc = EncryptedString()
        encrypted = enc.process_bind_param("secret", None)

        monkeypatch.setenv("SAUTIRIS_ENCRYPTION_KEY", key2)
        enc2 = EncryptedString()
        # Fernet-encrypted values (starting with "gAAAAA") must raise DecryptionError
        # on wrong key — returning ciphertext as plaintext would silently corrupt data.
        with pytest.raises(DecryptionError):
            enc2.process_result_value(encrypted, None)


class TestConfigValidation:
    """Startup validation for security settings (issues #4, #6)."""

    def test_cors_wildcard_with_credentials_raises(self) -> None:
        from sautiris.config import ConfigurationError, SautiRISSettings

        settings = SautiRISSettings(
            cors_origins=["*"],
            cors_allow_credentials=True,
            database_url="sqlite+aiosqlite:///:memory:",
        )
        with pytest.raises(ConfigurationError, match="wildcard"):
            settings.validate_security()

    def test_cors_wildcard_without_credentials_ok(self) -> None:
        from sautiris.config import SautiRISSettings

        settings = SautiRISSettings(
            cors_origins=["*"],
            cors_allow_credentials=False,
            database_url="sqlite+aiosqlite:///:memory:",
        )
        settings.validate_security()  # should not raise

    def test_production_missing_encryption_key_raises(self) -> None:
        from sautiris.config import ConfigurationError, SautiRISSettings

        settings = SautiRISSettings(
            environment="production",
            encryption_key="",
            database_url="sqlite+aiosqlite:///:memory:",
        )
        with pytest.raises(ConfigurationError, match="SAUTIRIS_ENCRYPTION_KEY"):
            settings.validate_security()

    def test_production_with_encryption_key_ok(self) -> None:
        from cryptography.fernet import Fernet

        from sautiris.config import SautiRISSettings

        key = Fernet.generate_key().decode()
        settings = SautiRISSettings(
            environment="production",
            encryption_key=key,
            database_url="sqlite+aiosqlite:///:memory:",
        )
        settings.validate_security()  # should not raise

    # -----------------------------------------------------------------------
    # GAP-I8: development environment edge cases
    # -----------------------------------------------------------------------

    def test_development_without_encryption_key_does_not_raise(self) -> None:
        """GAP-I8: development environment with no encryption key passes validate_security.

        Only production requires an encryption key.  Developers without a key
        configured must not be blocked by validate_security.
        """
        from sautiris.config import SautiRISSettings

        settings = SautiRISSettings(
            environment="development",
            encryption_key="",  # no key — acceptable in development
            database_url="sqlite+aiosqlite:///:memory:",
        )
        settings.validate_security()  # must NOT raise

    def test_staging_without_encryption_key_does_not_raise(self) -> None:
        """GAP-I8: staging environment without encryption key passes validate_security.

        The security gate only blocks production.  Staging is allowed to run
        without encryption so staging environments can be bootstrapped easily.
        """
        from sautiris.config import SautiRISSettings

        settings = SautiRISSettings(
            environment="staging",
            encryption_key="",
            database_url="sqlite+aiosqlite:///:memory:",
        )
        settings.validate_security()  # must NOT raise

    def test_development_with_cors_specific_origins_ok(self) -> None:
        """Development with specific CORS origins (no wildcard) passes validate_security."""
        from sautiris.config import SautiRISSettings

        settings = SautiRISSettings(
            environment="development",
            cors_origins=["http://localhost:3000", "http://localhost:8080"],
            cors_allow_credentials=True,
            database_url="sqlite+aiosqlite:///:memory:",
        )
        settings.validate_security()  # specific origins with credentials is OK


# ---------------------------------------------------------------------------
# R2-H9: Corrupted Fernet ciphertext handling
# ---------------------------------------------------------------------------


class TestCorruptedFernetCiphertext:
    """EncryptedString must raise DecryptionError on corrupted Fernet tokens."""

    def test_corrupted_fernet_token_raises_decryption_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A value starting with 'gAAAAA' but with corrupted content raises DecryptionError."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("SAUTIRIS_ENCRYPTION_KEY", key)
        enc = EncryptedString()

        # Corrupt a real Fernet token by mangling bytes in the middle
        real_encrypted = enc.process_bind_param("real_secret", None)
        assert real_encrypted is not None
        # Corrupt by replacing characters in the middle
        corrupted = real_encrypted[:15] + "XXXX_CORRUPTED" + real_encrypted[29:]

        # Must raise DecryptionError, not silently return corrupted data
        with pytest.raises(DecryptionError, match="could not be decrypted"):
            enc.process_result_value(corrupted, None)

    def test_fernet_prefix_without_valid_content_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A value that starts with gAAAAA but isn't valid Fernet raises DecryptionError."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("SAUTIRIS_ENCRYPTION_KEY", key)
        enc = EncryptedString()

        with pytest.raises(DecryptionError):
            enc.process_result_value("gAAAAABthis_is_not_valid_fernet_at_all", None)


# ---------------------------------------------------------------------------
# R2-C4: Key rotation — skipped plaintext + decrypt error handling
# ---------------------------------------------------------------------------


class TestKeyRotationDetailedResults:
    """rotate_encryption_key_detailed returns rotated_count and skipped_count."""

    def test_rotation_skips_plaintext_and_logs_warning(self) -> None:
        """Plaintext values are skipped with a warning; skipped_count is incremented."""
        from unittest.mock import MagicMock

        from cryptography.fernet import Fernet

        from sautiris.core.crypto import (
            _ENCRYPTED_COLUMNS,
            KeyRotationResult,
            rotate_encryption_key_detailed,
        )

        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        # Build a mock connection that returns one row with a plaintext value
        mock_conn = MagicMock()
        # For each table, return a row with id + one plaintext column value
        row_data = []
        for _table, columns in _ENCRYPTED_COLUMNS:
            row = ["row-id-1"] + ["plaintext_value"] * len(columns)
            row_data.append([tuple(row)])

        call_idx = {"i": 0}

        def _mock_execute(stmt, params=None):
            result = MagicMock()
            if "SELECT" in str(stmt):
                idx = call_idx["i"]
                call_idx["i"] += 1
                result.fetchall.return_value = row_data[idx] if idx < len(row_data) else []
            return result

        mock_conn.execute = _mock_execute

        result = rotate_encryption_key_detailed(mock_conn, old_key, new_key)
        assert isinstance(result, KeyRotationResult)
        assert result.rotated_count == 0
        assert result.skipped_count > 0

    def test_rotation_raises_on_corrupted_ciphertext(self) -> None:
        """DecryptionError raised when old key can't decrypt a Fernet-looking value."""
        from unittest.mock import MagicMock

        from cryptography.fernet import Fernet

        from sautiris.core.crypto import (
            _ENCRYPTED_COLUMNS,
            _FERNET_PREFIX,
            rotate_encryption_key_detailed,
        )

        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        # Build fake Fernet token (right prefix, wrong content)
        fake_fernet = _FERNET_PREFIX + "AAAA_NOT_REAL_FERNET_DATA_HERE=="

        mock_conn = MagicMock()
        row_data = []
        for _table, columns in _ENCRYPTED_COLUMNS:
            row = ["row-id-1"] + [fake_fernet] * len(columns)
            row_data.append([tuple(row)])

        call_idx = {"i": 0}

        def _mock_execute(stmt, params=None):
            result = MagicMock()
            if "SELECT" in str(stmt):
                idx = call_idx["i"]
                call_idx["i"] += 1
                result.fetchall.return_value = row_data[idx] if idx < len(row_data) else []
            return result

        mock_conn.execute = _mock_execute

        with pytest.raises(DecryptionError, match="Failed to decrypt"):
            rotate_encryption_key_detailed(mock_conn, old_key, new_key)
