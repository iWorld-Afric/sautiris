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
