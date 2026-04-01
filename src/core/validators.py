"""PAGAL OS Input Validators — centralized validation for all user inputs.

Provides reusable validation functions for agent names, tasks, ratings,
file paths, and share codes. Each function returns a (valid, error_message)
tuple so callers can handle failures gracefully.
"""

import re
from pathlib import Path

# Regex patterns
_AGENT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{1,50}$")
_SHARE_CODE_PATTERN = re.compile(r"^[A-Z0-9]{8}$")
_PATH_TRAVERSAL = re.compile(r"(^|[\\/])\.\.($|[\\/])")

# Limits
MAX_TASK_LENGTH = 10_000
MAX_AGENT_NAME_LENGTH = 50
MIN_RATING = 1
MAX_RATING = 5


def validate_agent_name(name: str) -> tuple[bool, str]:
    """Validate an agent name: alphanumeric + underscore, 1-50 chars.

    Args:
        name: The agent name to validate.

    Returns:
        Tuple of (valid, error_message). error_message is empty if valid.
    """
    if not name:
        return False, "Agent name cannot be empty."
    if len(name) > MAX_AGENT_NAME_LENGTH:
        return False, f"Agent name must be at most {MAX_AGENT_NAME_LENGTH} characters."
    if not _AGENT_NAME_PATTERN.match(name):
        return False, (
            "Agent name must contain only alphanumeric characters and "
            "underscores (a-z, A-Z, 0-9, _)."
        )
    return True, ""


def validate_task(task: str) -> tuple[bool, str]:
    """Validate a task description: non-empty, max 10,000 chars.

    Args:
        task: The task text to validate.

    Returns:
        Tuple of (valid, error_message).
    """
    if not task or not task.strip():
        return False, "Task cannot be empty."
    if len(task) > MAX_TASK_LENGTH:
        return False, f"Task must be at most {MAX_TASK_LENGTH} characters (got {len(task)})."
    return True, ""


def validate_rating(rating: int) -> tuple[bool, str]:
    """Validate a rating: integer 1-5.

    Args:
        rating: The rating value to validate.

    Returns:
        Tuple of (valid, error_message).
    """
    if not isinstance(rating, int):
        return False, f"Rating must be an integer, got {type(rating).__name__}."
    if rating < MIN_RATING or rating > MAX_RATING:
        return False, f"Rating must be between {MIN_RATING} and {MAX_RATING} (got {rating})."
    return True, ""


def validate_file_path(path: str) -> tuple[bool, str]:
    """Validate a file path: no path traversal (..) allowed.

    Args:
        path: The file path to validate.

    Returns:
        Tuple of (valid, error_message).
    """
    if not path or not path.strip():
        return False, "File path cannot be empty."
    if _PATH_TRAVERSAL.search(path):
        return False, "File path must not contain '..' (path traversal)."
    return True, ""


def validate_share_code(code: str) -> tuple[bool, str]:
    """Validate a share code: exactly 8 uppercase alphanumeric chars.

    Args:
        code: The share code to validate.

    Returns:
        Tuple of (valid, error_message).
    """
    if not code:
        return False, "Share code cannot be empty."
    if not _SHARE_CODE_PATTERN.match(code.upper()):
        return False, "Share code must be exactly 8 alphanumeric characters."
    return True, ""
