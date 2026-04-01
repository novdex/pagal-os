"""Telegram channel -- talk to PAGAL OS agents from Telegram.

Uses httpx for lightweight HTTP calls to the Telegram Bot API.
No external Telegram library required.
"""

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("pagal_os")

# Per-chat active agent: chat_id -> agent_name
_chat_agents: dict[int, str] = {}

# Telegram Bot API base URL
_TELEGRAM_API = "https://api.telegram.org/bot{token}"


def send_telegram_message(bot_token: str, chat_id: int | str, text: str) -> bool:
    """Send a message to a Telegram chat via the Bot API.

    Args:
        bot_token: The Telegram bot token.
        chat_id: Target chat ID (integer or string).
        text: Message text to send.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    url = f"{_TELEGRAM_API.format(token=bot_token)}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                logger.warning("Telegram sendMessage failed: %s", data)
                return False
            return True
    except httpx.HTTPStatusError as e:
        # If Markdown parsing fails, retry without parse_mode
        logger.warning("Telegram send failed with Markdown, retrying plain: %s", e)
        try:
            payload.pop("parse_mode", None)
            with httpx.Client(timeout=15) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json().get("ok", False)
        except Exception as retry_err:
            logger.error("Telegram send retry failed: %s", retry_err)
            return False
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)
        return False


def _command_handler(
    bot_token: str,
    chat_id: int,
    text: str,
    username: str,
    default_agent: str,
) -> str | None:
    """Handle Telegram bot commands (messages starting with /).

    Supported commands:
        /start      - Welcome message
        /agents     - List available agents
        /use <name> - Switch to a different agent
        /hands      - List active hands
        /hand start <agent> every <schedule> <task> - Start a hand
        /hand stop <agent> - Stop a hand
        /help       - Show help text

    Args:
        bot_token: Telegram bot token (for sending messages).
        chat_id: The chat ID from which the command was sent.
        text: The full command text.
        username: Telegram username of the sender.
        default_agent: Default agent name for new chats.

    Returns:
        Response text if it is a command, or None if not a command.
    """
    text = text.strip()
    if not text.startswith("/"):
        return None

    parts = text.split(maxsplit=1)
    command = parts[0].lower().split("@")[0]  # Handle /command@botname
    args_text = parts[1] if len(parts) > 1 else ""

    if command == "/start":
        return (
            f"Welcome to *PAGAL OS*, {username or 'friend'}!\n\n"
            f"You are talking to agent: *{_chat_agents.get(chat_id, default_agent)}*\n\n"
            "Commands:\n"
            "/agents - List available agents\n"
            "/use <agent> - Switch agent\n"
            "/hands - List scheduled hands\n"
            "/help - Show this help"
        )

    if command == "/help":
        return (
            "*PAGAL OS Telegram Bot*\n\n"
            "Just type a message and your active agent will respond.\n\n"
            "Commands:\n"
            "/agents - List all agents\n"
            "/use <agent> - Switch to an agent\n"
            "/hands - List active hands\n"
            "/hand start <agent> every <schedule> <task>\n"
            "/hand stop <agent>\n"
            "/help - Show this help"
        )

    if command == "/agents":
        try:
            from src.core.runtime import list_agents
            agents = list_agents()
            if not agents:
                return "No agents found. Create one first!"
            lines = ["*Available Agents:*\n"]
            for a in agents:
                status_icon = "[running]" if a["status"] == "running" else "[idle]"
                lines.append(f"  `{a['name']}` {status_icon} - {a.get('description', '')[:50]}")
            current = _chat_agents.get(chat_id, default_agent)
            lines.append(f"\nActive agent: *{current}*")
            lines.append("Switch with: /use <agent_name>")
            return "\n".join(lines)
        except Exception as e:
            logger.error("Failed to list agents for Telegram: %s", e)
            return f"Error listing agents: {e}"

    if command == "/use":
        agent_name = args_text.strip()
        if not agent_name:
            return "Usage: /use <agent_name>\nExample: /use research_agent"
        try:
            from src.core.runtime import load_agent
            load_agent(agent_name)
            _chat_agents[chat_id] = agent_name
            return f"Switched to agent: *{agent_name}*"
        except FileNotFoundError:
            return f"Agent '{agent_name}' not found. Use /agents to see available agents."
        except Exception as e:
            return f"Error switching agent: {e}"

    if command == "/hands":
        try:
            from src.core.hands import list_hands
            hands = list_hands()
            if not hands:
                return "No active hands. Start one with:\n/hand start <agent> every <schedule> <task>"
            lines = ["*Active Hands:*\n"]
            for h in hands:
                lines.append(
                    f"  `{h['agent']}` [{h['status']}]\n"
                    f"    Schedule: {h['schedule']}\n"
                    f"    Task: {h['task'][:60]}\n"
                    f"    Last run: {h.get('last_run', 'never')}"
                )
            return "\n".join(lines)
        except Exception as e:
            logger.error("Failed to list hands for Telegram: %s", e)
            return f"Error listing hands: {e}"

    if command == "/hand":
        return _handle_hand_command(args_text)

    return f"Unknown command: {command}\nUse /help to see available commands."


def _handle_hand_command(args_text: str) -> str:
    """Handle /hand start and /hand stop subcommands.

    Args:
        args_text: Everything after '/hand '.

    Returns:
        Response text.
    """
    parts = args_text.strip().split(maxsplit=1)
    if not parts:
        return "Usage:\n/hand start <agent> every <schedule> <task>\n/hand stop <agent>"

    subcmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if subcmd == "stop":
        agent_name = rest.strip()
        if not agent_name:
            return "Usage: /hand stop <agent_name>"
        try:
            from src.core.hands import stop_hand
            if stop_hand(agent_name):
                return f"Hand '{agent_name}' stopped."
            return f"Hand '{agent_name}' is not running."
        except Exception as e:
            return f"Error stopping hand: {e}"

    if subcmd == "start":
        # Parse: <agent> every <schedule> <task>
        # Or: <agent> daily at HH:MM <task>
        import re
        # Try "every" pattern: agent_name every Xm/h/d task text
        match = re.match(r"(\S+)\s+(every\s+\d+\s*[smhd])\s+(.+)", rest, re.IGNORECASE)
        if not match:
            # Try "daily at" pattern: agent_name daily at HH:MM task text
            match = re.match(r"(\S+)\s+(daily\s+at\s+\d{1,2}:\d{2})\s+(.+)", rest, re.IGNORECASE)
        if not match:
            return (
                "Usage: /hand start <agent> every <schedule> <task>\n"
                "Example: /hand start research_agent every 1h find AI news"
            )

        agent_name = match.group(1)
        schedule = match.group(2)
        task = match.group(3)

        try:
            from src.core.hands import start_hand
            result = start_hand(agent_name, schedule, task)
            if result.get("ok"):
                return (
                    f"Hand started!\n"
                    f"Agent: *{agent_name}*\n"
                    f"Schedule: {schedule}\n"
                    f"Task: {task}"
                )
            return f"Failed to start hand: {result.get('error', 'unknown error')}"
        except Exception as e:
            return f"Error starting hand: {e}"

    return "Usage:\n/hand start <agent> every <schedule> <task>\n/hand stop <agent>"


def handle_telegram_message(
    bot_token: str,
    chat_id: int,
    text: str,
    username: str,
    default_agent: str,
) -> str:
    """Route a Telegram message to an agent and return the response.

    First checks if the message is a command. If not, routes it to
    the user's currently active agent.

    Args:
        bot_token: Telegram bot token.
        chat_id: Telegram chat ID.
        text: The message text from the user.
        username: Telegram username of the sender.
        default_agent: Default agent name for new chats.

    Returns:
        Response text from the agent or command handler.
    """
    # Check for commands first
    cmd_response = _command_handler(bot_token, chat_id, text, username, default_agent)
    if cmd_response is not None:
        return cmd_response

    # Route to the active agent for this chat
    agent_name = _chat_agents.get(chat_id, default_agent)

    try:
        from src.core.runtime import load_agent, run_agent

        agent = load_agent(agent_name)
        result = run_agent(agent, text)

        if result.ok:
            response = result.output or "(Agent returned empty response)"
            # Truncate long responses for Telegram (max 4096 chars)
            if len(response) > 4000:
                response = response[:3997] + "..."
            return response
        else:
            return f"Agent error: {result.error}"

    except FileNotFoundError:
        return (
            f"Agent '{agent_name}' not found.\n"
            "Use /agents to see available agents, or /use <agent> to switch."
        )
    except Exception as e:
        logger.error("Error handling Telegram message for agent '%s': %s", agent_name, e)
        return f"Error: {e}"


def start_telegram_bot(bot_token: str, default_agent: str = "research_agent") -> None:
    """Start polling for Telegram messages and route them to agents.

    Uses long polling via getUpdates. Runs forever until interrupted.

    Args:
        bot_token: Telegram bot token from BotFather.
        default_agent: Default agent to use for new chats.
    """
    if not bot_token or bot_token == "your_token":
        logger.error("Invalid Telegram bot token. Set TELEGRAM_BOT_TOKEN in .env.")
        print("Error: Set TELEGRAM_BOT_TOKEN in your .env file.")
        print("Get a token from @BotFather on Telegram.")
        return

    base_url = _TELEGRAM_API.format(token=bot_token)
    offset: int | None = None
    poll_timeout = 30  # Long polling timeout in seconds

    logger.info("Starting Telegram bot (default agent: %s)...", default_agent)
    print(f"Telegram bot started! Default agent: {default_agent}")
    print("Send /start to your bot on Telegram to begin.")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            params: dict[str, Any] = {"timeout": poll_timeout}
            if offset is not None:
                params["offset"] = offset

            with httpx.Client(timeout=poll_timeout + 10) as client:
                resp = client.get(f"{base_url}/getUpdates", params=params)
                resp.raise_for_status()
                data = resp.json()

            if not data.get("ok"):
                logger.warning("Telegram getUpdates returned not ok: %s", data)
                time.sleep(5)
                continue

            updates = data.get("result", [])

            for update in updates:
                update_id = update.get("update_id", 0)
                offset = update_id + 1

                message = update.get("message")
                if not message:
                    continue

                chat_id = message.get("chat", {}).get("id")
                text = message.get("text", "")
                username = message.get("from", {}).get("username", "")
                first_name = message.get("from", {}).get("first_name", "")
                display_name = username or first_name or "user"

                if not chat_id or not text:
                    continue

                logger.info(
                    "Telegram message from %s (chat %s): %s",
                    display_name, chat_id, text[:100],
                )

                # Process message and send response
                try:
                    response = handle_telegram_message(
                        bot_token, chat_id, text, display_name, default_agent,
                    )
                    send_telegram_message(bot_token, chat_id, response)
                except Exception as e:
                    logger.error("Error processing Telegram update: %s", e, exc_info=True)
                    try:
                        send_telegram_message(
                            bot_token, chat_id,
                            f"Sorry, something went wrong: {e}",
                        )
                    except Exception:
                        pass

        except httpx.TimeoutException:
            # Normal for long polling -- just retry
            continue
        except KeyboardInterrupt:
            logger.info("Telegram bot stopped by user.")
            print("\nTelegram bot stopped.")
            break
        except Exception as e:
            logger.error("Telegram polling error: %s", e, exc_info=True)
            time.sleep(5)
