"""PAGAL OS Shell Tool — execute shell commands with timeout and sandboxing.

Blocks dangerous commands (recursive deletes, system shutdowns, fork bombs,
etc.) and strips sensitive environment variables before execution. Every
command is audit-logged.
"""

import logging
import os
import re
import shlex
import subprocess
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


# ---------------------------------------------------------------------------
# Sandboxing configuration
# ---------------------------------------------------------------------------

# Exact substring matches — if any of these appear in the command, block it.
BLOCKED_COMMANDS: list[str] = [
    "rm -rf", "rm -r", "del /f", "format", "shutdown", "reboot",
    "mkfs", "dd if=", ":(){ :|:& };:", "sudo rm", "sudo su",
    "powershell -enc", "cmd /c del", "rmdir /s",
    "chmod 777", "chown root", "passwd",
]

# Regex patterns — checked after the substring pass.
BLOCKED_PATTERNS: list[str] = [
    r";\s*rm\s",           # command chaining with rm
    r"&&\s*rm\s",          # command chaining with rm
    r"\|\s*rm\s",          # piped into rm
    r">\s*/dev/",          # redirect to system devices
    r">\s*C:\\Windows",    # redirect to system dirs (Windows)
    r"\$\(.*rm\s",         # command substitution with rm
    r"`.*rm\s",            # backtick substitution with rm
    r"curl\s.*\|\s*sh",    # pipe curl to shell
    r"wget\s.*\|\s*sh",    # pipe wget to shell
    r"curl\s.*\|\s*bash",  # pipe curl to bash
    r"wget\s.*\|\s*bash",  # pipe wget to bash
    r"python\s+-c\s",      # arbitrary python execution
    r"perl\s+-e\s",        # arbitrary perl execution
    r"ruby\s+-e\s",        # arbitrary ruby execution
    r"nc\s+-l",            # netcat listener
    r"ncat\s",             # ncat usage
]

# Environment variable names that should never leak to child processes.
_SENSITIVE_ENV_KEYS: set[str] = {
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "SECRET_KEY",
    "DATABASE_URL",
}


def _is_blocked(command: str) -> str | None:
    """Check whether a command is blocked by the sandbox policy.

    Args:
        command: The raw shell command string.

    Returns:
        A human-readable reason string if blocked, or None if allowed.
    """
    lower = command.lower()

    # Substring checks
    for blocked in BLOCKED_COMMANDS:
        if blocked.lower() in lower:
            return f"Blocked command pattern: '{blocked}'"

    # Regex checks
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return f"Blocked command pattern: '{pattern}'"

    return None


def _safe_env() -> dict[str, str]:
    """Build a copy of the environment with sensitive keys removed.

    Returns:
        A dict of environment variables safe for child processes.
    """
    return {
        k: v for k, v in os.environ.items()
        if k.upper() not in _SENSITIVE_ENV_KEYS
    }


def _audit_shell(command: str, blocked: bool = False, reason: str = "") -> None:
    """Write an audit log entry for a shell command.

    Args:
        command: The command string.
        blocked: Whether the command was blocked.
        reason: Reason for blocking (if applicable).
    """
    try:
        from src.core.security import audit_log

        if blocked:
            audit_log("shell_blocked", "shell_tool", f"cmd={command[:200]} reason={reason}")
        else:
            audit_log("shell_exec", "shell_tool", f"cmd={command[:200]}")
    except Exception as e:
        logger.debug("Audit log unavailable for shell: %s", e)


def run_shell(command: str, timeout: int = 10) -> dict[str, Any]:
    """Run a shell command with sandboxing, timeout, and audit logging.

    Before execution:
    1. Checks the command against BLOCKED_COMMANDS (substring match).
    2. Checks against BLOCKED_PATTERNS (regex match).
    3. Strips sensitive environment variables from the child process.
    4. Applies timeout (already existed).
    5. Logs the command to the audit log.

    Args:
        command: The shell command to execute.
        timeout: Maximum execution time in seconds (default: 10).

    Returns:
        Dict with 'ok', 'result' (stdout), 'stderr', and 'returncode' keys.
    """
    # --- Sandbox check ---
    blocked_reason = _is_blocked(command)
    if blocked_reason:
        logger.warning("Shell command blocked: %s — %s", command[:120], blocked_reason)
        _audit_shell(command, blocked=True, reason=blocked_reason)
        return {
            "ok": False,
            "error": f"Command blocked by sandbox: {blocked_reason}",
            "result": "",
        }

    # --- Audit log ---
    _audit_shell(command)

    try:
        logger.info("Running shell command: %s", command[:200])

        # Use shlex.split to avoid shell=True where possible.
        # Fall back to shell=True only for commands that need shell features
        # (pipes, redirects, globs, etc.)
        needs_shell = any(ch in command for ch in ("|", ">", "<", "*", "~", "&&", "||"))
        if needs_shell:
            cmd_args: str | list[str] = command
        else:
            try:
                cmd_args = shlex.split(command)
            except ValueError:
                cmd_args = command
                needs_shell = True

        result = subprocess.run(
            cmd_args,
            shell=needs_shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_safe_env(),
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
    description="Run a shell command and return the output. Commands are sandboxed — dangerous operations are blocked.",
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
