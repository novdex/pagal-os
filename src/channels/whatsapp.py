"""PAGAL OS WhatsApp Channel — connect agents to WhatsApp via Business Cloud API.

Uses the official WhatsApp Business Cloud API (Meta). Requires:
  - WHATSAPP_TOKEN: API access token from Meta developer dashboard
  - WHATSAPP_PHONE_ID: Your WhatsApp Business phone number ID
  - WHATSAPP_VERIFY_TOKEN: Webhook verification token (you choose this)

Setup:
  1. Create a Meta Developer account and WhatsApp Business app
  2. Get your access token and phone number ID
  3. Set the webhook URL to: https://your-server/api/whatsapp/webhook
  4. Set the environment variables above
"""

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("pagal_os")

# Configuration from environment
_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "pagal-os-whatsapp")
_API_URL = "https://graph.facebook.com/v21.0"

# Per-chat agent mapping: phone_number -> agent_name
_chat_agents: dict[str, str] = {}
_default_agent = "research_assistant"


def send_message(to: str, text: str) -> dict[str, Any]:
    """Send a text message via WhatsApp Business API.

    Args:
        to: Recipient phone number (with country code, e.g. '919876543210').
        text: Message text to send.

    Returns:
        Dict with 'ok' and response data.
    """
    if not _TOKEN or not _PHONE_ID:
        return {"ok": False, "error": "WHATSAPP_TOKEN and WHATSAPP_PHONE_ID must be set"}

    try:
        url = f"{_API_URL}/{_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text[:4096]},  # WhatsApp limit
        }

        with httpx.Client(timeout=15) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()

        logger.info("WhatsApp message sent to %s", to)
        return {"ok": True, "data": response.json()}

    except Exception as e:
        logger.error("WhatsApp send failed: %s", e)
        return {"ok": False, "error": str(e)}


def verify_webhook(mode: str, token: str, challenge: str) -> str | None:
    """Verify the webhook subscription from Meta.

    Args:
        mode: Should be 'subscribe'.
        token: The verify token (must match WHATSAPP_VERIFY_TOKEN).
        challenge: The challenge string to return.

    Returns:
        The challenge string if valid, None otherwise.
    """
    if mode == "subscribe" and token == _VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified")
        return challenge
    logger.warning("WhatsApp webhook verification failed")
    return None


def handle_webhook(payload: dict[str, Any]) -> None:
    """Process an incoming WhatsApp webhook event.

    Extracts the message, runs it through the assigned agent, and sends
    the reply back.

    Args:
        payload: The webhook JSON payload from Meta.
    """
    try:
        entry = payload.get("entry", [])
        if not entry:
            return

        for e in entry:
            changes = e.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    if msg.get("type") != "text":
                        continue

                    sender = msg.get("from", "")
                    text = msg.get("text", {}).get("body", "")

                    if not sender or not text:
                        continue

                    logger.info("WhatsApp message from %s: %s", sender, text[:100])

                    # Handle commands
                    if text.startswith("/"):
                        response = _handle_command(sender, text)
                    else:
                        response = _run_agent(sender, text)

                    if response:
                        send_message(sender, response)

    except Exception as e:
        logger.error("WhatsApp webhook handling failed: %s", e)


def _handle_command(sender: str, text: str) -> str:
    """Handle WhatsApp commands.

    Supported commands:
        /agents — list available agents
        /use <name> — switch to a different agent
        /help — show help
    """
    parts = text.strip().split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        return (
            "*PAGAL OS on WhatsApp*\n\n"
            "Just send a message and your AI agent will respond.\n\n"
            "Commands:\n"
            "/agents — list available agents\n"
            "/use <name> — switch agent\n"
            "/help — show this help"
        )

    if command == "/agents":
        try:
            from src.core.runtime import list_agents
            agents = list_agents()
            if not agents:
                return "No agents found. Install one from the dashboard."
            lines = ["*Available Agents:*\n"]
            for a in agents:
                lines.append(f"  {a['name']} — {a.get('description', '')[:50]}")
            current = _chat_agents.get(sender, _default_agent)
            lines.append(f"\nCurrent: *{current}*")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "/use":
        agent_name = args.strip()
        if not agent_name:
            return "Usage: /use <agent_name>"
        try:
            from src.core.validators import validate_agent_name
            valid, err = validate_agent_name(agent_name)
            if not valid:
                return f"Invalid name: {err}"
            from src.core.runtime import load_agent
            load_agent(agent_name)
            _chat_agents[sender] = agent_name
            return f"Switched to agent: *{agent_name}*"
        except FileNotFoundError:
            return f"Agent '{agent_name}' not found."
        except Exception as e:
            return f"Error: {e}"

    return "Unknown command. Type /help for available commands."


def _run_agent(sender: str, text: str) -> str:
    """Run the assigned agent on the user's message."""
    try:
        from src.core.runtime import load_agent, run_agent

        agent_name = _chat_agents.get(sender, _default_agent)
        agent = load_agent(agent_name)
        result = run_agent(agent, text)

        if result.ok:
            return result.output[:4096] if result.output else "Agent completed but returned no output."
        return f"Error: {result.error}"

    except FileNotFoundError:
        return f"Agent '{_chat_agents.get(sender, _default_agent)}' not found. Use /agents to see available agents."
    except Exception as e:
        logger.error("WhatsApp agent run failed: %s", e)
        return f"Something went wrong: {e}"
