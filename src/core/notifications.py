"""Notifications — alert users about agent activity.

Push notifications when agents complete, need approval, or encounter errors.
Stored in ~/.pagal-os/notifications.json. Optionally sends to Telegram.
"""

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Storage
_PAGAL_DIR = Path.home() / ".pagal-os"
NOTIFICATIONS_FILE = _PAGAL_DIR / "notifications.json"


@dataclass
class Notification:
    """A single notification entry."""

    id: str
    type: str  # completed, approval, error, info
    agent_name: str
    message: str
    read: bool = False
    timestamp: str = ""

    def __post_init__(self) -> None:
        """Set default timestamp if not provided."""
        if not self.timestamp:
            self.timestamp = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
            )


def _load_notifications() -> list[dict[str, Any]]:
    """Load all notifications from disk.

    Returns:
        List of notification dicts.
    """
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        if not NOTIFICATIONS_FILE.exists():
            NOTIFICATIONS_FILE.write_text("[]", encoding="utf-8")
            return []
        data = json.loads(NOTIFICATIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error("Failed to load notifications: %s", e)
        return []


def _save_notifications(notifications: list[dict[str, Any]]) -> None:
    """Persist notifications to disk.

    Args:
        notifications: Full list of notification dicts.
    """
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        NOTIFICATIONS_FILE.write_text(
            json.dumps(notifications, indent=2), encoding="utf-8",
        )
    except Exception as e:
        logger.error("Failed to save notifications: %s", e)


def _try_telegram(message: str) -> None:
    """Attempt to send a notification via Telegram if configured.

    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
    Silently skips if not configured.

    Args:
        message: Text message to send.
    """
    try:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not bot_token or not chat_id:
            return

        from src.channels.telegram import send_telegram_message
        send_telegram_message(bot_token, chat_id, f"[PAGAL OS] {message}")
    except Exception as e:
        logger.debug("Telegram notification failed: %s", e)


def send_notification(
    notification_type: str,
    agent_name: str,
    message: str,
) -> str:
    """Create a notification and optionally send to Telegram.

    Args:
        notification_type: One of 'completed', 'approval', 'error', 'info'.
        agent_name: Name of the agent.
        message: The notification message.

    Returns:
        The notification ID.
    """
    try:
        notif = Notification(
            id=str(uuid.uuid4())[:8],
            type=notification_type,
            agent_name=agent_name,
            message=message,
        )

        notifications = _load_notifications()
        notifications.insert(0, asdict(notif))  # newest first
        _save_notifications(notifications)

        # Try Telegram in background
        _try_telegram(f"[{notification_type.upper()}] {agent_name}: {message}")

        logger.info(
            "Notification [%s] for '%s': %s",
            notification_type, agent_name, message[:80],
        )
        return notif.id

    except Exception as e:
        logger.error("Failed to send notification: %s", e)
        return ""


def get_notifications(
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get notifications, optionally filtered to unread only.

    Args:
        unread_only: If True, return only unread notifications.
        limit: Maximum number of notifications to return.

    Returns:
        List of notification dicts, newest first.
    """
    try:
        notifications = _load_notifications()

        if unread_only:
            notifications = [n for n in notifications if not n.get("read", False)]

        return notifications[:limit]

    except Exception as e:
        logger.error("Failed to get notifications: %s", e)
        return []


def mark_read(notification_id: str) -> bool:
    """Mark a single notification as read.

    Args:
        notification_id: The notification ID.

    Returns:
        True if found and marked, False otherwise.
    """
    try:
        notifications = _load_notifications()

        for notif in notifications:
            if notif.get("id") == notification_id:
                notif["read"] = True
                _save_notifications(notifications)
                return True

        return False

    except Exception as e:
        logger.error("Failed to mark notification read: %s", e)
        return False


def mark_all_read() -> bool:
    """Mark all notifications as read.

    Returns:
        True if successful.
    """
    try:
        notifications = _load_notifications()

        for notif in notifications:
            notif["read"] = True

        _save_notifications(notifications)
        return True

    except Exception as e:
        logger.error("Failed to mark all notifications read: %s", e)
        return False


def get_unread_count() -> int:
    """Get the number of unread notifications.

    Returns:
        Count of unread notifications.
    """
    try:
        notifications = _load_notifications()
        return sum(1 for n in notifications if not n.get("read", False))
    except Exception as e:
        logger.error("Failed to get unread count: %s", e)
        return 0


def clear_old_notifications(days: int = 7) -> None:
    """Delete notifications older than the specified number of days.

    Args:
        days: Delete notifications older than this many days.
    """
    try:
        import datetime

        notifications = _load_notifications()
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        kept = [
            n for n in notifications
            if n.get("timestamp", "9999") > cutoff_str
        ]

        removed = len(notifications) - len(kept)
        if removed > 0:
            _save_notifications(kept)
            logger.info("Cleared %d old notifications", removed)

    except Exception as e:
        logger.error("Failed to clear old notifications: %s", e)
