"""PAGAL OS Encrypted Agent Storage — protect agent memory and configs at rest.

Uses the ``cryptography`` library's Fernet symmetric encryption (AES-128-CBC
with HMAC-SHA256 for authentication). Encrypted files carry a ``PAGAL_ENC:``
header followed by a Fernet token.

The Fernet key is auto-generated on first use and stored at
``~/.pagal-os/.encryption_key``.
"""

import logging
from pathlib import Path
from typing import Any

from src.core.config import get_config

logger = logging.getLogger("pagal_os")

# Encryption header to identify PAGAL-encrypted files
ENC_HEADER = "PAGAL_ENC:"

# Key file location
KEY_FILE = Path.home() / ".pagal-os" / ".encryption_key"


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


def generate_key() -> str:
    """Generate a Fernet encryption key and save it to disk.

    The key is a URL-safe base64-encoded 32-byte key suitable for Fernet.
    Written to ``~/.pagal-os/.encryption_key``. If the file already exists
    it is **not** overwritten.

    Returns:
        The generated (or existing) key string.
    """
    try:
        from cryptography.fernet import Fernet

        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)

        if KEY_FILE.exists():
            logger.info("Encryption key already exists at %s", KEY_FILE)
            return KEY_FILE.read_text(encoding="utf-8").strip()

        key = Fernet.generate_key().decode()
        KEY_FILE.write_text(key, encoding="utf-8")
        # Best-effort permission restriction (Unix-only; no-op on Windows)
        try:
            KEY_FILE.chmod(0o600)
        except Exception:
            pass
        logger.info("Generated Fernet encryption key at %s", KEY_FILE)
        return key
    except Exception as e:
        logger.error("Failed to generate encryption key: %s", e)
        raise


def load_key() -> str:
    """Load the encryption key from disk, generating one if needed.

    Returns:
        The Fernet key string.
    """
    try:
        if KEY_FILE.exists():
            return KEY_FILE.read_text(encoding="utf-8").strip()
        return generate_key()
    except Exception as e:
        logger.error("Failed to load encryption key: %s", e)
        raise


# ---------------------------------------------------------------------------
# Low-level encrypt / decrypt
# ---------------------------------------------------------------------------


def encrypt_data(data: str, key: str | None = None) -> str:
    """Encrypt a string using Fernet symmetric encryption.

    Args:
        data: Plaintext string to encrypt.
        key: Optional Fernet key. Uses the stored key if None.

    Returns:
        Fernet token string (URL-safe base64).
    """
    try:
        from cryptography.fernet import Fernet

        if key is None:
            key = load_key()
        f = Fernet(key.encode() if isinstance(key, str) else key)
        return f.encrypt(data.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("Encryption failed: %s", e)
        raise


def decrypt_data(encrypted: str, key: str | None = None) -> str:
    """Decrypt a Fernet token back to plaintext.

    Args:
        encrypted: Fernet token string.
        key: Optional Fernet key. Uses the stored key if None.

    Returns:
        Decrypted plaintext string.
    """
    try:
        from cryptography.fernet import Fernet

        if key is None:
            key = load_key()
        f = Fernet(key.encode() if isinstance(key, str) else key)
        return f.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("Decryption failed: %s", e)
        raise


# ---------------------------------------------------------------------------
# File-level operations
# ---------------------------------------------------------------------------


def is_encrypted(file_path: str | Path) -> bool:
    """Check whether a file is PAGAL-encrypted (carries the header).

    Args:
        file_path: Path to the file.

    Returns:
        True if the file starts with the ``PAGAL_ENC:`` header.
    """
    try:
        p = Path(file_path)
        if not p.exists():
            return False
        content = p.read_text(encoding="utf-8")
        return content.startswith(ENC_HEADER)
    except Exception:
        return False


def encrypt_file(file_path: str | Path) -> bool:
    """Encrypt a file in-place (prepending the ``PAGAL_ENC:`` header).

    If the file is already encrypted, this is a no-op.

    Args:
        file_path: Path to the file to encrypt.

    Returns:
        True if encrypted successfully (or already encrypted).
    """
    try:
        p = Path(file_path)
        if not p.exists():
            logger.warning("File not found for encryption: %s", p)
            return False

        if is_encrypted(p):
            logger.debug("File already encrypted: %s", p)
            return True

        plaintext = p.read_text(encoding="utf-8")
        token = encrypt_data(plaintext)
        p.write_text(f"{ENC_HEADER}{token}", encoding="utf-8")
        logger.info("Encrypted file: %s", p)
        return True
    except Exception as e:
        logger.error("Failed to encrypt file %s: %s", file_path, e)
        return False


def decrypt_file(file_path: str | Path) -> str:
    """Decrypt a PAGAL-encrypted file and return the plaintext.

    Does **not** modify the file on disk.

    Args:
        file_path: Path to the encrypted file.

    Returns:
        Decrypted plaintext content.

    Raises:
        ValueError: If the file is not encrypted.
    """
    try:
        p = Path(file_path)
        content = p.read_text(encoding="utf-8")

        if not content.startswith(ENC_HEADER):
            raise ValueError(f"File is not encrypted: {p}")

        token = content[len(ENC_HEADER):]
        return decrypt_data(token)
    except ValueError:
        raise
    except Exception as e:
        logger.error("Failed to decrypt file %s: %s", file_path, e)
        raise


# ---------------------------------------------------------------------------
# Agent-level helpers
# ---------------------------------------------------------------------------


def encrypt_agent_memory(agent_name: str) -> bool:
    """Encrypt all memory files for an agent.

    Looks in ``~/.pagal-os/memory/`` for files matching the agent name.

    Args:
        agent_name: Name of the agent whose memory to encrypt.

    Returns:
        True if at least one file was encrypted.
    """
    try:
        config = get_config()
        memory_dir = config.memory_dir
        if not memory_dir.exists():
            logger.warning("Memory directory does not exist: %s", memory_dir)
            return False

        encrypted_any = False
        # Encrypt any file that references this agent
        for f in memory_dir.iterdir():
            if f.is_file() and agent_name in f.name:
                if encrypt_file(f):
                    encrypted_any = True

        # Also encrypt the agent's YAML config
        agent_yaml = config.agents_dir / f"{agent_name}.yaml"
        if agent_yaml.exists():
            if encrypt_file(agent_yaml):
                encrypted_any = True

        if encrypted_any:
            logger.info("Encrypted memory/config for agent '%s'", agent_name)
        else:
            logger.info("No files found to encrypt for agent '%s'", agent_name)

        return encrypted_any
    except Exception as e:
        logger.error("Failed to encrypt memory for '%s': %s", agent_name, e)
        return False


def decrypt_agent_memory(agent_name: str) -> list[dict[str, Any]]:
    """Decrypt and return all encrypted memory files for an agent.

    Does **not** modify files on disk.

    Args:
        agent_name: Name of the agent.

    Returns:
        List of dicts with ``file`` and ``content`` keys.
    """
    results: list[dict[str, Any]] = []
    try:
        config = get_config()
        memory_dir = config.memory_dir

        # Check memory directory
        if memory_dir.exists():
            for f in memory_dir.iterdir():
                if f.is_file() and agent_name in f.name and is_encrypted(f):
                    try:
                        plaintext = decrypt_file(f)
                        results.append({"file": str(f), "content": plaintext})
                    except Exception as e:
                        results.append({"file": str(f), "error": str(e)})

        # Check agent YAML
        agent_yaml = config.agents_dir / f"{agent_name}.yaml"
        if agent_yaml.exists() and is_encrypted(agent_yaml):
            try:
                plaintext = decrypt_file(agent_yaml)
                results.append({"file": str(agent_yaml), "content": plaintext})
            except Exception as e:
                results.append({"file": str(agent_yaml), "error": str(e)})

        return results
    except Exception as e:
        logger.error("Failed to decrypt memory for '%s': %s", agent_name, e)
        return results
