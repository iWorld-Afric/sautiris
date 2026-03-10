"""Performance tests for Fernet field-level encryption.

Validates that per-field encrypt/decrypt latency is acceptable for PHI storage patterns.
Run with: python -m pytest tests/test_performance/ -x -q -m performance
"""

from __future__ import annotations

import time

import pytest
from cryptography.fernet import Fernet

from sautiris.core.crypto import EncryptedString, _fernet_decrypt, _fernet_encrypt


@pytest.fixture
def fernet_key() -> str:
    """Generate a fresh Fernet key for each test."""
    return Fernet.generate_key().decode()


@pytest.mark.performance
class TestCryptoPerformance:
    """Performance tests for Fernet-based field encryption."""

    def test_fernet_encrypt_single_latency(self, fernet_key: str) -> None:
        """Single Fernet encryption must complete in < 10ms.

        PHI column writes trigger encrypt on each row INSERT/UPDATE.
        Threshold of 10ms gives headroom above typical ~0.1-1ms Fernet time.
        """
        plaintext = "John Doe — MRN#12345678 — DOB 1970-01-01"
        start = time.perf_counter()
        _fernet_encrypt(plaintext, fernet_key)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.010, (
            f"Single Fernet encrypt took {elapsed * 1000:.3f}ms — expected < 10ms."
        )

    def test_fernet_decrypt_single_latency(self, fernet_key: str) -> None:
        """Single Fernet decryption must complete in < 10ms."""
        plaintext = "John Doe — MRN#12345678 — DOB 1970-01-01"
        ciphertext = _fernet_encrypt(plaintext, fernet_key)

        start = time.perf_counter()
        result = _fernet_decrypt(ciphertext, fernet_key)
        elapsed = time.perf_counter() - start

        assert result == plaintext
        assert elapsed < 0.010, (
            f"Single Fernet decrypt took {elapsed * 1000:.3f}ms — expected < 10ms."
        )

    def test_fernet_1000_encrypt_decrypt_cycles(self, fernet_key: str) -> None:
        """1000 encrypt+decrypt round-trips must complete in < 5s.

        Establishes a throughput baseline: 200 round-trips/s minimum.
        A radiology order typically encrypts ~5-10 PHI fields per write.
        At 200 round-trips/s, that's 20-40 orders/s — sufficient for a single RIS node.
        """
        plaintext = "Patient: Jane Smith, MRN: 98765432, DOB: 1985-06-15"
        n = 1000

        start = time.perf_counter()
        for _ in range(n):
            ct = _fernet_encrypt(plaintext, fernet_key)
            _fernet_decrypt(ct, fernet_key)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, (
            f"{n} encrypt+decrypt cycles took {elapsed:.3f}s — expected < 5s. "
            f"Throughput: {n / elapsed:.0f} round-trips/s."
        )

    def test_encrypted_string_type_decorator_overhead(
        self, fernet_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EncryptedString TypeDecorator bind/result cycle must add < 10ms per field."""
        monkeypatch.setenv("SAUTIRIS_ENCRYPTION_KEY", fernet_key)
        enc = EncryptedString()
        plaintext = "Sensitive radiology note — confidential PHI content"

        start = time.perf_counter()
        encrypted = enc.process_bind_param(plaintext, None)
        assert encrypted is not None
        decrypted = enc.process_result_value(encrypted, None)
        elapsed = time.perf_counter() - start

        assert decrypted == plaintext
        assert elapsed < 0.010, (
            f"EncryptedString bind+result cycle took {elapsed * 1000:.3f}ms — expected < 10ms."
        )

    def test_encrypted_string_no_key_passthrough_is_zero_cost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When SAUTIRIS_ENCRYPTION_KEY is unset, passthrough must have negligible overhead."""
        monkeypatch.delenv("SAUTIRIS_ENCRYPTION_KEY", raising=False)
        enc = EncryptedString()
        plaintext = "dev-plaintext-value"

        n = 10_000
        start = time.perf_counter()
        for _ in range(n):
            enc.process_bind_param(plaintext, None)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, (
            f"{n} no-op passthroughs took {elapsed:.3f}s — expected < 0.5s. "
            "No-key path should be just an env var read and string return."
        )

    def test_fernet_key_caching_not_required_for_performance(self, fernet_key: str) -> None:
        """Verify that creating a new Fernet() per call doesn't cause excessive overhead.

        The current implementation creates Fernet() on each call (no caching).
        This test verifies that 500 such calls stay under 2s, establishing
        whether key caching is needed as an optimization.
        """
        plaintext = "test-phi-value"
        n = 500

        start = time.perf_counter()
        for _ in range(n):
            _fernet_encrypt(plaintext, fernet_key)
        elapsed = time.perf_counter() - start

        # If this is too slow, consider caching Fernet(key) by key hash
        assert elapsed < 2.0, (
            f"{n} encrypt calls (each creating Fernet()) took {elapsed:.3f}s — expected < 2s. "
            "If this fails, Fernet() construction overhead may warrant key caching."
        )

    def test_large_payload_encryption_latency(self, fernet_key: str) -> None:
        """Encrypting a large report text (10KB) must complete in < 50ms."""
        # Simulate a long radiology report
        large_payload = "This is a detailed radiology report. " * 300  # ~10KB
        assert len(large_payload) >= 10_000, "Payload should be at least 10KB"

        start = time.perf_counter()
        ciphertext = _fernet_encrypt(large_payload, fernet_key)
        elapsed_enc = time.perf_counter() - start

        assert elapsed_enc < 0.050, (
            f"10KB encryption took {elapsed_enc * 1000:.2f}ms — expected < 50ms."
        )

        start = time.perf_counter()
        decrypted = _fernet_decrypt(ciphertext, fernet_key)
        elapsed_dec = time.perf_counter() - start

        assert decrypted == large_payload
        assert elapsed_dec < 0.050, (
            f"10KB decryption took {elapsed_dec * 1000:.2f}ms — expected < 50ms."
        )
