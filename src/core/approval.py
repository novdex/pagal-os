"""Human-in-the-Loop — agents ask permission for risky actions.

Provides an approval gate system that pauses agent execution before
risky tool calls (file writes, shell commands, clicks) and waits for
human approval via CLI, Telegram, or web dashboard.
"""

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Paths
_PAGAL_DIR = Path.home() / ".pagal-os"
_APPROVALS_FILE = _PAGAL_DIR / "approvals.json"

# Risky tools that require human approval by default
_RISKY_TOOLS: set[str] = {
    "write_file",
    "run_shell",
    "click",
    "delete_file",
    "execute_command",
}

# In-memory store for pending approvals
_pending_approvals: dict[str, dict[str, Any]] = {}


def _load_approvals() -> dict[str, dict[str, Any]]:
    """Load persisted approvals from disk.

    Returns:
        Dict mapping approval_id to approval info.
    """
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        if _APPROVALS_FILE.exists():
            data = json.loads(_APPROVALS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("Failed to load approvals: %s", e)
    return {}


def _save_approvals() -> None:
    """Persist current pending approvals to disk."""
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        _APPROVALS_FILE.write_text(
            json.dumps(_pending_approvals, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error("Failed to save approvals: %s", e)


def needs_approval(tool_name: str, args: dict[str, Any], approval_mode: str = "ask") -> bool:
    """Check whether a tool call requires human approval.

    Args:
        tool_name: Name of the tool being called.
        args: Arguments passed to the tool.
        approval_mode: One of "ask" (risky only), "auto" (never ask),
                       "strict" (ask for ALL tools).

    Returns:
        True if human approval is needed before executing this tool.
    """
    try:
        if approval_mode == "auto":
            return False
        if approval_mode == "strict":
            return True
        # Default "ask" mode: only risky tools
        return tool_name in _RISKY_TOOLS
    except Exception as e:
        logger.error("Error checking approval need: %s", e)
        return False


def request_approval(
    agent_name: str,
    tool_name: str,
    args: dict[str, Any],
    channel: str = "web",
) -> bool:
    """Send an approval request and wait for a response.

    For CLI: prints a prompt and waits for y/n input.
    For web/Telegram: stores the request in _pending_approvals and returns
    False immediately (the caller should poll or await).

    Args:
        agent_name: The agent requesting approval.
        tool_name: The tool the agent wants to call.
        args: The arguments for the tool call.
        channel: Delivery channel — "cli", "web", or "telegram".

    Returns:
        True if approved, False if denied or pending.
    """
    try:
        approval_id = str(uuid.uuid4())[:8]

        # Build human-readable description
        description = _format_approval_message(tool_name, args)

        approval_entry: dict[str, Any] = {
            "id": approval_id,
            "agent": agent_name,
            "tool": tool_name,
            "args": args,
            "description": description,
            "status": "pending",
            "timestamp": time.time(),
            "channel": channel,
        }

        if channel == "cli":
            # Synchronous CLI approval
            print(f"\n[APPROVAL REQUIRED] Agent '{agent_name}':")
            print(f"  {description}")
            try:
                response = input("  Allow? [y/n]: ").strip().lower()
                approved = response in ("y", "yes")
                approval_entry["status"] = "approved" if approved else "denied"
                logger.info(
                    "CLI approval for %s/%s: %s",
                    agent_name, tool_name, approval_entry["status"],
                )
                return approved
            except (EOFError, KeyboardInterrupt):
                approval_entry["status"] = "denied"
                return False
        else:
            # Async approval (web/telegram): store and return False
            _pending_approvals[approval_id] = approval_entry
            _save_approvals()
            logger.info(
                "Approval request %s created for %s/%s (channel=%s)",
                approval_id, agent_name, tool_name, channel,
            )
            return False

    except Exception as e:
        logger.error("Failed to request approval: %s", e)
        return False


def get_pending_approvals() -> list[dict[str, Any]]:
    """List all pending approval requests.

    Returns:
        List of approval dicts with id, agent, tool, args, description,
        status, and timestamp.
    """
    try:
        return [
            entry for entry in _pending_approvals.values()
            if entry.get("status") == "pending"
        ]
    except Exception as e:
        logger.error("Failed to get pending approvals: %s", e)
        return []


def approve(approval_id: str) -> bool:
    """Approve a pending action.

    Args:
        approval_id: The unique ID of the approval request.

    Returns:
        True if the approval was found and updated, False otherwise.
    """
    try:
        if approval_id in _pending_approvals:
            _pending_approvals[approval_id]["status"] = "approved"
            _pending_approvals[approval_id]["resolved_at"] = time.time()
            _save_approvals()
            logger.info("Approval %s approved", approval_id)
            return True
        logger.warning("Approval %s not found", approval_id)
        return False
    except Exception as e:
        logger.error("Failed to approve %s: %s", approval_id, e)
        return False


def deny(approval_id: str) -> bool:
    """Deny a pending action.

    Args:
        approval_id: The unique ID of the approval request.

    Returns:
        True if the denial was recorded, False otherwise.
    """
    try:
        if approval_id in _pending_approvals:
            _pending_approvals[approval_id]["status"] = "denied"
            _pending_approvals[approval_id]["resolved_at"] = time.time()
            _save_approvals()
            logger.info("Approval %s denied", approval_id)
            return True
        logger.warning("Approval %s not found", approval_id)
        return False
    except Exception as e:
        logger.error("Failed to deny %s: %s", approval_id, e)
        return False


def get_approval_status(approval_id: str) -> str:
    """Get the current status of an approval request.

    Args:
        approval_id: The unique ID of the approval request.

    Returns:
        Status string: "pending", "approved", "denied", or "not_found".
    """
    try:
        entry = _pending_approvals.get(approval_id)
        if entry:
            return entry.get("status", "pending")
        return "not_found"
    except Exception as e:
        logger.error("Failed to get approval status: %s", e)
        return "not_found"


def _format_approval_message(tool_name: str, args: dict[str, Any]) -> str:
    """Generate a human-readable description of a tool call.

    Args:
        tool_name: The tool being called.
        args: The tool arguments.

    Returns:
        Formatted description string.
    """
    try:
        if tool_name == "write_file":
            path = args.get("path", args.get("file_path", "unknown"))
            return f"Agent wants to write to {path}. Allow? [y/n]"
        elif tool_name == "run_shell":
            command = args.get("command", args.get("cmd", "unknown"))
            return f"Agent wants to run: {command}. Allow? [y/n]"
        elif tool_name == "click":
            x = args.get("x", "?")
            y = args.get("y", "?")
            return f"Agent wants to click at ({x},{y}). Allow? [y/n]"
        elif tool_name == "delete_file":
            path = args.get("path", args.get("file_path", "unknown"))
            return f"Agent wants to delete {path}. Allow? [y/n]"
        else:
            return f"Agent wants to call {tool_name}({json.dumps(args, default=str)[:200]}). Allow? [y/n]"
    except Exception:
        return f"Agent wants to call {tool_name}. Allow? [y/n]"
