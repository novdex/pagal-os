"""PAGAL OS File Tools — read and write files."""

import logging
from pathlib import Path
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")

# Directories that agents are allowed to access.
# Resolved at import time; additional paths can be added via config.
_PAGAL_DIR = Path.home() / ".pagal-os"
_ALLOWED_ROOTS: list[Path] = [
    _PAGAL_DIR,
    Path("/tmp"),
    Path.cwd(),
]

# Sensitive paths that must never be read/written, even inside allowed roots.
_BLOCKED_NAMES = {
    ".env", ".env.local", ".env.production",
    "credentials.json", "secrets.yaml", "id_rsa", "id_ed25519",
    ".encryption_key",
}
_BLOCKED_PREFIXES = [
    Path.home() / ".ssh",
    Path.home() / ".aws",
    Path.home() / ".gnupg",
    Path.home() / ".config" / "gcloud",
]


def _is_path_allowed(file_path: Path) -> str | None:
    """Return an error message if *file_path* is outside the sandbox, else None."""
    resolved = file_path.resolve()

    # Block sensitive filenames
    if resolved.name.lower() in _BLOCKED_NAMES:
        return f"Access denied (sensitive file): {resolved.name}"

    # Block sensitive directories
    for prefix in _BLOCKED_PREFIXES:
        try:
            resolved.relative_to(prefix.resolve())
            return f"Access denied (sensitive directory): {prefix}"
        except ValueError:
            pass

    # Ensure path is inside at least one allowed root
    for root in _ALLOWED_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return None
        except ValueError:
            pass

    return (
        f"Access denied: path '{resolved}' is outside allowed directories. "
        f"Agents may only access files under {', '.join(str(r) for r in _ALLOWED_ROOTS)}."
    )


def read_file(path: str) -> dict[str, Any]:
    """Read the contents of a file.

    Args:
        path: Absolute or relative path to the file.

    Returns:
        Dict with 'ok' and 'result' (file contents string) keys.
    """
    try:
        file_path = Path(path).expanduser().resolve()

        # Path boundary check
        access_error = _is_path_allowed(file_path)
        if access_error:
            logger.warning("File read blocked: %s", access_error)
            return {"ok": False, "error": access_error}

        if not file_path.exists():
            return {"ok": False, "error": f"File not found: {file_path}"}

        if not file_path.is_file():
            return {"ok": False, "error": f"Not a file: {file_path}"}

        # Limit file size to 1MB
        if file_path.stat().st_size > 1_048_576:
            return {"ok": False, "error": f"File too large (>1MB): {file_path}"}

        content = file_path.read_text(encoding="utf-8")
        logger.info("Read file: %s (%d chars)", file_path, len(content))
        return {"ok": True, "result": content}

    except UnicodeDecodeError:
        return {"ok": False, "error": f"Cannot read binary file: {path}"}
    except Exception as e:
        logger.error("Failed to read file '%s': %s", path, e)
        return {"ok": False, "error": f"Read failed: {e}"}


def write_file(path: str, content: str) -> dict[str, Any]:
    """Write content to a file, creating directories as needed.

    Args:
        path: Absolute or relative path to the file.
        content: String content to write.

    Returns:
        Dict with 'ok' and 'result' (success message) keys.
    """
    try:
        file_path = Path(path).expanduser().resolve()

        # Path boundary check
        access_error = _is_path_allowed(file_path)
        if access_error:
            logger.warning("File write blocked: %s", access_error)
            return {"ok": False, "error": access_error}

        # Create parent directories
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_text(content, encoding="utf-8")
        logger.info("Wrote file: %s (%d chars)", file_path, len(content))
        return {"ok": True, "result": f"Written {len(content)} chars to {file_path}"}

    except Exception as e:
        logger.error("Failed to write file '%s': %s", path, e)
        return {"ok": False, "error": f"Write failed: {e}"}


# Auto-register on import
register_tool(
    name="read_file",
    function=read_file,
    description="Read the contents of a file from the filesystem.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read",
            },
        },
        "required": ["path"],
    },
)

register_tool(
    name="write_file",
    function=write_file,
    description="Write content to a file, creating parent directories as needed.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file",
            },
        },
        "required": ["path", "content"],
    },
)
