"""Tests for PAGAL OS encryption module (Fernet-based)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import encryption as enc_module


@pytest.fixture(autouse=True)
def isolate_encryption(tmp_path: Path):
    """Redirect the encryption key file to a temp directory for each test."""
    test_key_file = tmp_path / ".encryption_key"
    # Write a valid Fernet key
    test_key = Fernet.generate_key().decode()
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

    def test_encrypt_with_explicit_key(self) -> None:
        """Should encrypt/decrypt with an explicitly provided key."""
        key = Fernet.generate_key().decode()
        plaintext = "explicit key test"
        encrypted = enc_module.encrypt_data(plaintext, key=key)
        decrypted = enc_module.decrypt_data(encrypted, key=key)
        assert decrypted == plaintext


class TestWrongPassword:
    """Test behavior with wrong decryption password."""

    def test_wrong_password_fails(self, tmp_path: Path) -> None:
        """Decrypting with a different key should raise an error."""
        # Encrypt with the current key
        plaintext = "Super secret data"
        encrypted = enc_module.encrypt_data(plaintext)

        # Change the key to a different valid Fernet key
        wrong_key_file = tmp_path / ".wrong_key"
        wrong_key = Fernet.generate_key().decode()
        wrong_key_file.write_text(wrong_key, encoding="utf-8")

        with patch.object(enc_module, "KEY_FILE", wrong_key_file):
            # Fernet should raise InvalidToken with the wrong key
            with pytest.raises(Exception):
                enc_module.decrypt_data(encrypted)


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


class TestGenerateKey:
    """Test Fernet key generation."""

    def test_generate_key_creates_valid_fernet_key(self, tmp_path: Path) -> None:
        """Generated key should be a valid Fernet key."""
        key_file = tmp_path / ".new_key"
        with patch.object(enc_module, "KEY_FILE", key_file):
            key = enc_module.generate_key()
            # Should not raise — valid Fernet key
            Fernet(key.encode())

    def test_generate_key_idempotent(self) -> None:
        """Calling generate_key twice should return the same key."""
        key1 = enc_module.generate_key()
        key2 = enc_module.generate_key()
        assert key1 == key2
