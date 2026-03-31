"""PAGAL OS File Tools — read and write files."""

import logging
from pathlib import Path
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


def read_file(path: str) -> dict[str, Any]:
    """Read the contents of a file.

    Args:
        path: Absolute or relative path to the file.

    Returns:
        Dict with 'ok' and 'result' (file contents string) keys.
    """
    try:
        file_path = Path(path).expanduser().resolve()

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
