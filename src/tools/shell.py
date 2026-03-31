"""PAGAL OS Shell Tool — execute shell commands with timeout."""

import logging
import subprocess
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


def run_shell(command: str, timeout: int = 10) -> dict[str, Any]:
    """Run a shell command and capture its output.

    Args:
        command: The shell command to execute.
        timeout: Maximum execution time in seconds (default: 10).

    Returns:
        Dict with 'ok', 'result' (stdout), 'stderr', and 'returncode' keys.
    """
    try:
        logger.info("Running shell command: %s", command)

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = {
            "ok": result.returncode == 0,
            "result": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }

        if result.returncode != 0:
            output["error"] = f"Command exited with code {result.returncode}"

        return output

    except subprocess.TimeoutExpired:
        logger.warning("Shell command timed out after %ds: %s", timeout, command)
        return {"ok": False, "error": f"Command timed out after {timeout}s", "result": ""}
    except Exception as e:
        logger.error("Shell command failed: %s", e)
        return {"ok": False, "error": f"Shell error: {e}", "result": ""}


# Auto-register on import
register_tool(
    name="run_shell",
    function=run_shell,
    description="Run a shell command and return the output. Use with caution.",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum execution time in seconds (default: 10)",
                "default": 10,
            },
        },
        "required": ["command"],
    },
)
