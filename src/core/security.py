"""Security layers for PAGAL OS — prompt injection detection, input
sanitisation, file access control, audit logging, and rate limiting.
"""

import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Paths
_PAGAL_DIR = Path.home() / ".pagal-os"
AUDIT_LOG_FILE = _PAGAL_DIR / "audit.log"

# Rate-limit tracking: agent_name -> list of timestamps
_rate_buckets: dict[str, list[float]] = defaultdict(list)

# --- Prompt Injection Detection ---

# Common prompt-injection patterns (case-insensitive)
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(prior|above)\s+", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+are\b", re.IGNORECASE),
    re.compile(r"act\s+as\s+if\s+you", re.IGNORECASE),
    re.compile(r"override\s+(your\s+)?(rules|safety|guidelines)", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow\s+(your|any)\s+(rules|instructions)", re.IGNORECASE),
]


def scan_prompt_injection(text: str) -> dict[str, Any]:
    """Detect common prompt-injection patterns in *text*.

    Args:
        text: The user message or prompt to scan.

    Returns:
        Dict with 'safe' (bool) and 'threats' (list of matched pattern
        descriptions).
    """
    try:
        threats: list[str] = []
        for pattern in _INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                threats.append(f"Pattern matched: '{match.group()}'")

        safe = len(threats) == 0
        if not safe:
            logger.warning("Prompt injection detected: %s", threats)

        return {"safe": safe, "threats": threats}
    except Exception as e:
        logger.error("Prompt injection scan failed: %s", e)
        # Fail open so agents don't stall, but log the error
        return {"safe": True, "threats": []}


# --- Tool Input Sanitisation ---

# Dangerous shell meta-characters
_DANGEROUS_SHELL_CHARS = re.compile(r"[;&|`$]")
# Path traversal
_PATH_TRAVERSAL = re.compile(r"(^|/)\.\.(/|$)")
# SQL injection hints
_SQL_INJECTION = re.compile(r"('--|;\s*DROP|;\s*DELETE|;\s*UPDATE|;\s*INSERT)", re.IGNORECASE)


def sanitize_tool_input(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Validate and sanitise tool arguments.

    Blocks path traversal, command injection, and SQL injection patterns.

    Args:
        tool_name: Name of the tool being called.
        args: Raw argument dict from the LLM.

    Returns:
        Sanitised copy of *args*.

    Raises:
        ValueError: If a dangerous pattern is found that cannot be stripped.
    """
    sanitized: dict[str, Any] = {}

    try:
        for key, value in args.items():
            if isinstance(value, str):
                # Check path traversal
                if _PATH_TRAVERSAL.search(value):
                    raise ValueError(
                        f"Path traversal blocked in {tool_name}.{key}: '{value}'"
                    )

                # Check command injection for shell-related tools
                if tool_name in ("run_shell", "shell", "exec"):
                    if _DANGEROUS_SHELL_CHARS.search(value):
                        raise ValueError(
                            f"Command injection blocked in {tool_name}.{key}: '{value}'"
                        )

                # Check SQL injection
                if _SQL_INJECTION.search(value):
                    raise ValueError(
                        f"SQL injection blocked in {tool_name}.{key}: '{value}'"
                    )

                sanitized[key] = value
            else:
                sanitized[key] = value

        return sanitized
    except ValueError:
        raise
    except Exception as e:
        logger.error("Tool input sanitisation failed: %s", e)
        return args


# --- File Access Control ---

# Blocked directory prefixes (normalised to lowercase for Windows)
_BLOCKED_UNIX = ["/etc", "/sys", "/proc", "/boot", "/root"]
_BLOCKED_WINDOWS = [
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
]
_BLOCKED_FILES = [".env", ".env.local", ".env.production", "credentials.json", "secrets.yaml"]


def check_file_access(path: str) -> bool:
    """Check whether *path* is within allowed directories.

    Blocks system directories and sensitive dotfiles.

    Args:
        path: File path to check.

    Returns:
        True if access is allowed, False if blocked.
    """
    try:
        resolved = Path(path).resolve()
        resolved_str = str(resolved)
        resolved_lower = resolved_str.lower()

        # Block Unix system dirs
        for blocked in _BLOCKED_UNIX:
            if resolved_lower.startswith(blocked):
                logger.warning("File access blocked (system dir): %s", path)
                return False

        # Block Windows system dirs
        for blocked in _BLOCKED_WINDOWS:
            if resolved_lower.startswith(blocked):
                logger.warning("File access blocked (system dir): %s", path)
                return False

        # Block sensitive files by name
        filename = resolved.name.lower()
        if filename in _BLOCKED_FILES:
            logger.warning("File access blocked (sensitive file): %s", path)
            return False

        return True
    except Exception as e:
        logger.error("File access check failed: %s", e)
        return False


# --- Audit Logging ---


def audit_log(event: str, agent: str, details: str = "") -> None:
    """Append an entry to the audit log file.

    Args:
        event: Event type (e.g. "tool_call", "llm_call", "security_block").
        agent: Agent name performing the action.
        details: Additional information about the event.
    """
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"[{timestamp}] agent={agent} event={event} {details}\n"
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.error("Audit log write failed: %s", e)


def get_audit_entries(limit: int = 100) -> list[str]:
    """Read recent entries from the audit log.

    Args:
        limit: Maximum number of lines to return (newest first).

    Returns:
        List of log line strings.
    """
    try:
        if not AUDIT_LOG_FILE.exists():
            return []
        lines = AUDIT_LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
        return list(reversed(lines[-limit:]))
    except Exception as e:
        logger.error("Failed to read audit log: %s", e)
        return []


# --- Rate Limiting ---


def rate_limit(agent_name: str, max_per_minute: int = 30) -> bool:
    """Check whether *agent_name* is under the per-minute rate limit.

    Args:
        agent_name: The agent to check.
        max_per_minute: Maximum allowed actions per 60-second window.

    Returns:
        True if the agent is under the limit (allowed), False if over.
    """
    try:
        now = time.time()
        cutoff = now - 60.0

        # Prune old entries
        _rate_buckets[agent_name] = [
            t for t in _rate_buckets[agent_name] if t > cutoff
        ]

        if len(_rate_buckets[agent_name]) >= max_per_minute:
            logger.warning(
                "Rate limit exceeded for agent '%s': %d/%d per minute",
                agent_name,
                len(_rate_buckets[agent_name]),
                max_per_minute,
            )
            return False

        _rate_buckets[agent_name].append(now)
        return True
    except Exception as e:
        logger.error("Rate limit check failed: %s", e)
        # Fail open
        return True
