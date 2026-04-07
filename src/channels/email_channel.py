"""PAGAL OS Email Channel — agents can read and send emails via IMAP/SMTP.

Configure via environment variables:
  EMAIL_IMAP_HOST, EMAIL_IMAP_PORT (default 993)
  EMAIL_SMTP_HOST, EMAIL_SMTP_PORT (default 587)
  EMAIL_ADDRESS, EMAIL_PASSWORD

Provides tools for agents to interact with email.
"""

import email
import imaplib
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")

# Config from environment
_IMAP_HOST = os.getenv("EMAIL_IMAP_HOST", "")
_IMAP_PORT = int(os.getenv("EMAIL_IMAP_PORT", "993"))
_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "")
_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
_EMAIL_ADDR = os.getenv("EMAIL_ADDRESS", "")
_EMAIL_PASS = os.getenv("EMAIL_PASSWORD", "")


def _check_config() -> str | None:
    """Return an error message if email is not configured, else None."""
    if not all([_IMAP_HOST, _SMTP_HOST, _EMAIL_ADDR, _EMAIL_PASS]):
        return "Email not configured. Set EMAIL_IMAP_HOST, EMAIL_SMTP_HOST, EMAIL_ADDRESS, EMAIL_PASSWORD."
    return None


def read_emails(folder: str = "INBOX", count: int = 5, unread_only: bool = True) -> dict[str, Any]:
    """Read recent emails from the inbox.

    Args:
        folder: IMAP folder to read (default: INBOX).
        count: Number of emails to fetch.
        unread_only: If True, only fetch unread emails.

    Returns:
        Dict with 'ok' and 'emails' list.
    """
    err = _check_config()
    if err:
        return {"ok": False, "error": err}

    try:
        mail = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
        mail.login(_EMAIL_ADDR, _EMAIL_PASS)
        mail.select(folder)

        search_criteria = "(UNSEEN)" if unread_only else "ALL"
        _, msg_ids = mail.search(None, search_criteria)
        ids = msg_ids[0].split()

        # Get the most recent N
        ids = ids[-count:] if len(ids) > count else ids

        emails: list[dict[str, str]] = []
        for mid in reversed(ids):
            _, data = mail.fetch(mid, "(RFC822)")
            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            # Extract body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

            emails.append({
                "from": msg.get("From", ""),
                "subject": msg.get("Subject", ""),
                "date": msg.get("Date", ""),
                "body": body[:2000],  # Limit body size
            })

        mail.logout()
        return {"ok": True, "emails": emails, "count": len(emails)}

    except Exception as e:
        logger.error("Email read failed: %s", e)
        return {"ok": False, "error": str(e)}


def send_email(to: str, subject: str, body: str) -> dict[str, Any]:
    """Send an email via SMTP.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text.

    Returns:
        Dict with 'ok' status.
    """
    err = _check_config()
    if err:
        return {"ok": False, "error": err}

    try:
        msg = MIMEMultipart()
        msg["From"] = _EMAIL_ADDR
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as server:
            server.starttls()
            server.login(_EMAIL_ADDR, _EMAIL_PASS)
            server.send_message(msg)

        logger.info("Email sent to %s: %s", to, subject)
        return {"ok": True, "message": f"Email sent to {to}"}

    except Exception as e:
        logger.error("Email send failed: %s", e)
        return {"ok": False, "error": str(e)}


# Auto-register tools
register_tool(
    name="read_emails",
    function=read_emails,
    description="Read recent emails from your inbox. Returns sender, subject, date, and body for each email.",
    parameters={
        "type": "object",
        "properties": {
            "folder": {"type": "string", "description": "IMAP folder (default: INBOX)", "default": "INBOX"},
            "count": {"type": "integer", "description": "Number of emails to fetch (default: 5)", "default": 5},
            "unread_only": {"type": "boolean", "description": "Only fetch unread emails", "default": True},
        },
        "required": [],
    },
)

register_tool(
    name="send_email",
    function=send_email,
    description="Send an email to someone. Provide the recipient address, subject, and body text.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email body text"},
        },
        "required": ["to", "subject", "body"],
    },
)
