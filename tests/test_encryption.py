"""Tests for PAGAL OS encryption module."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import encryption as enc_module


@pytest.fixture(autouse=True)
def isolate_encryption(tmp_path: Path):
    """Redirect the encryption key file to a temp directory for each test."""
    test_key_file = tmp_path / ".encryption_key"
    # Write a known test key
    test_key = "TestPassword1234567890abcdefgh!!"
    test_key_file.write_text(test_key, encoding="utf-8")

    with patch.object(enc_module, "KEY_FILE", test_key_file):
        yield test_key_file


class TestEncryptDecryptRoundTrip:
    """Test encrypting and decrypting data."""

    def test_encrypt_decrypt_round_trip(self) -> None:
        """Should encrypt and decrypt back to the original plaintext."""
        plaintext = "Hello, this is a secret message!"
        encrypted = enc_module.encrypt_data(plaintext)

        # Encrypted should not equal plaintext
        assert encrypted != plaintext

        # Decrypt should return original
        decrypted = enc_module.decrypt_data(encrypted)
        assert decrypted == plaintext

    def test_encrypt_decrypt_unicode(self) -> None:
        """Should handle unicode characters correctly."""
        plaintext = "Unicode test: cafe, naive, resume, 42"
        encrypted = enc_module.encrypt_data(plaintext)
        decrypted = enc_module.decrypt_data(encrypted)
        assert decrypted == plaintext

    def test_encrypt_decrypt_empty_string(self) -> None:
        """Should handle empty strings."""
        plaintext = ""
        encrypted = enc_module.encrypt_data(plaintext)
        decrypted = enc_module.decrypt_data(encrypted)
        assert decrypted == plaintext

    def test_encrypt_decrypt_long_text(self) -> None:
        """Should handle text longer than the key."""
        plaintext = "A" * 10000
        encrypted = enc_module.encrypt_data(plaintext)
        decrypted = enc_module.decrypt_data(encrypted)
        assert decrypted == plaintext


class TestWrongPassword:
    """Test behavior with wrong decryption password."""

    def test_wrong_password_fails(self, tmp_path: Path) -> None:
        """Decrypting with a different key should produce garbage or error."""
        # Encrypt with the current key
        plaintext = "Super secret data"
        encrypted = enc_module.encrypt_data(plaintext)

        # Change the key
        wrong_key_file = tmp_path / ".wrong_key"
        wrong_key_file.write_text("WrongPassword1234567890abcdefgh!!", encoding="utf-8")

        with patch.object(enc_module, "KEY_FILE", wrong_key_file):
            # Decrypting should either error or produce different text
            try:
                decrypted = enc_module.decrypt_data(encrypted)
                # If it doesn't raise, the result should be different (garbled)
                assert decrypted != plaintext
            except Exception:
                # An exception is also acceptable — wrong key should fail
                pass


class TestIsEncrypted:
    """Test encrypted file detection."""

    def test_is_encrypted_detection(self, tmp_path: Path) -> None:
        """Should detect files with the PAGAL_ENC: header."""
        # Create an encrypted file
        encrypted_file = tmp_path / "encrypted.txt"
        encrypted_file.write_text(f"{enc_module.ENC_HEADER}base64data", encoding="utf-8")
        assert enc_module.is_encrypted(str(encrypted_file)) is True

        # Create a normal file
        normal_file = tmp_path / "normal.txt"
        normal_file.write_text("just normal content", encoding="utf-8")
        assert enc_module.is_encrypted(str(normal_file)) is False

    def test_is_encrypted_nonexistent_file(self) -> None:
        """Should return False for a nonexistent file."""
        assert enc_module.is_encrypted("/nonexistent/file.txt") is False

    def test_encrypt_and_detect_file(self, tmp_path: Path) -> None:
        """Should encrypt a file in-place and detect it as encrypted."""
        test_file = tmp_path / "to_encrypt.txt"
        test_file.write_text("secret content here", encoding="utf-8")

        assert enc_module.is_encrypted(str(test_file)) is False

        success = enc_module.encrypt_file(str(test_file))
        assert success is True
        assert enc_module.is_encrypted(str(test_file)) is True

        # Decrypt should return original content
        decrypted = enc_module.decrypt_file(str(test_file))
        assert decrypted == "secret content here"
