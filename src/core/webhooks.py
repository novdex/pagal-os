"""Webhook Triggers — agents triggered by external HTTP events.

Register webhooks that map to agents. When an external service
(GitHub, email, custom) sends a POST to the webhook URL, the
associated agent is triggered with the payload as task context.
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
_WEBHOOKS_FILE = _PAGAL_DIR / "webhooks.json"


def _load_webhooks() -> dict[str, dict[str, Any]]:
    """Load registered webhooks from disk.

    Returns:
        Dict mapping webhook_id to webhook config.
    """
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        if _WEBHOOKS_FILE.exists():
            data = json.loads(_WEBHOOKS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("Failed to load webhooks: %s", e)
    return {}


def _save_webhooks(webhooks: dict[str, dict[str, Any]]) -> None:
    """Persist webhooks to disk.

    Args:
        webhooks: Full webhook registry dict.
    """
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        _WEBHOOKS_FILE.write_text(
            json.dumps(webhooks, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error("Failed to save webhooks: %s", e)


def register_webhook(
    agent_name: str,
    event_type: str,
    config: dict[str, Any] | None = None,
) -> str:
    """Register a webhook trigger for an agent.

    Args:
        agent_name: The agent to trigger when the webhook fires.
        event_type: Type of event — "http", "github", "email", "custom".
        config: Optional extra config (e.g. GitHub secret, filters).

    Returns:
        The webhook URL path: /webhooks/{webhook_id}
    """
    try:
        webhooks = _load_webhooks()
        webhook_id = str(uuid.uuid4())[:8]

        webhooks[webhook_id] = {
            "id": webhook_id,
            "agent_name": agent_name,
            "event_type": event_type,
            "config": config or {},
            "created_at": time.time(),
            "last_triggered": None,
            "trigger_count": 0,
        }

        _save_webhooks(webhooks)
        from src.core.config import get_config
        cfg = get_config()
        base_url = getattr(cfg, "base_url", None) or f"http://localhost:{cfg.api_port}"
        url = f"{base_url}/webhooks/{webhook_id}"
        logger.info(
            "Registered webhook %s for agent '%s' (type=%s): %s",
            webhook_id, agent_name, event_type, url,
        )
        return url

    except Exception as e:
        logger.error("Failed to register webhook: %s", e)
        return ""


def handle_webhook(webhook_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Receive a webhook and trigger the associated agent.

    1. Finds the webhook registration
    2. Formats the payload into a task string
    3. Runs the associated agent with the task
    4. Returns the agent's result

    Args:
        webhook_id: The unique webhook identifier.
        payload: The POST body from the external service.

    Returns:
        Dict with ok, agent_name, output or error.
    """
    try:
        webhooks = _load_webhooks()

        if webhook_id not in webhooks:
            logger.warning("Webhook %s not found", webhook_id)
            return {"ok": False, "error": f"Webhook '{webhook_id}' not found"}

        webhook = webhooks[webhook_id]
        agent_name = webhook["agent_name"]
        event_type = webhook["event_type"]

        # Update trigger stats
        webhook["last_triggered"] = time.time()
        webhook["trigger_count"] = webhook.get("trigger_count", 0) + 1
        _save_webhooks(webhooks)

        # Format payload into a task description
        summary = _summarize_payload(event_type, payload)
        task = f"Webhook triggered: {event_type}. Payload: {summary}"

        # Run the agent
        try:
            from src.core.runtime import load_agent, run_agent

            agent = load_agent(agent_name)
            result = run_agent(agent, task)

            return {
                "ok": result.ok,
                "agent_name": agent_name,
                "webhook_id": webhook_id,
                "output": result.output,
                "tools_used": result.tools_used,
                "duration_seconds": result.duration_seconds,
                "error": result.error,
            }
        except FileNotFoundError:
            return {
                "ok": False,
                "error": f"Agent '{agent_name}' not found",
            }

    except Exception as e:
        logger.error("Failed to handle webhook %s: %s", webhook_id, e)
        return {"ok": False, "error": str(e)}


def list_webhooks() -> list[dict[str, Any]]:
    """List all registered webhooks.

    Returns:
        List of webhook config dicts.
    """
    try:
        webhooks = _load_webhooks()
        result: list[dict[str, Any]] = []
        for wh_id, wh in webhooks.items():
            result.append({
                "id": wh_id,
                "agent_name": wh.get("agent_name", ""),
                "event_type": wh.get("event_type", ""),
                "url": f"http://localhost:8080/webhooks/{wh_id}",
                "created_at": wh.get("created_at"),
                "last_triggered": wh.get("last_triggered"),
                "trigger_count": wh.get("trigger_count", 0),
            })
        return result
    except Exception as e:
        logger.error("Failed to list webhooks: %s", e)
        return []


def delete_webhook(webhook_id: str) -> bool:
    """Delete a registered webhook.

    Args:
        webhook_id: The webhook to remove.

    Returns:
        True if deleted, False if not found.
    """
    try:
        webhooks = _load_webhooks()
        if webhook_id in webhooks:
            del webhooks[webhook_id]
            _save_webhooks(webhooks)
            logger.info("Deleted webhook %s", webhook_id)
            return True
        logger.warning("Webhook %s not found for deletion", webhook_id)
        return False
    except Exception as e:
        logger.error("Failed to delete webhook %s: %s", webhook_id, e)
        return False


def _summarize_payload(event_type: str, payload: dict[str, Any]) -> str:
    """Create a human-readable summary of a webhook payload.

    Args:
        event_type: The webhook event type.
        payload: The raw POST payload.

    Returns:
        Summarised string (max 500 chars).
    """
    try:
        if event_type == "github":
            # Extract key GitHub webhook fields
            action = payload.get("action", "")
            repo = payload.get("repository", {}).get("full_name", "")
            sender = payload.get("sender", {}).get("login", "")
            ref = payload.get("ref", "")
            parts = [f"repo={repo}"]
            if action:
                parts.append(f"action={action}")
            if sender:
                parts.append(f"sender={sender}")
            if ref:
                parts.append(f"ref={ref}")
            # Include commit messages if push
            commits = payload.get("commits", [])
            if commits:
                msgs = [c.get("message", "")[:60] for c in commits[:3]]
                parts.append(f"commits=[{'; '.join(msgs)}]")
            return ", ".join(parts)[:500]

        elif event_type == "email":
            subject = payload.get("subject", "")
            sender = payload.get("from", payload.get("sender", ""))
            return f"from={sender}, subject={subject}"[:500]

        else:
            # Generic: dump a compact JSON summary
            text = json.dumps(payload, default=str)
            return text[:500]

    except Exception:
        return json.dumps(payload, default=str)[:500]
