"""Zapier/n8n Webhook Bridge — connect PAGAL OS agents to 8000+ apps.

Provides two-way integration:
  - INBOUND: External services (Zapier/n8n) POST to /api/webhook-bridge/run
    with an agent name and task. The agent runs and returns the result.
  - OUTBOUND: Agents can call external webhook URLs to trigger actions in
    other apps (Zapier Catch Hook, n8n Webhook, Make, etc.).

This gives agents access to Gmail, Slack, Sheets, Shopify, Stripe, etc.
without building individual integrations.
"""

import logging
from typing import Any

import httpx

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


def call_webhook(
    url: str,
    data: dict[str, Any] | None = None,
    method: str = "POST",
) -> dict[str, Any]:
    """Call an external webhook URL (Zapier Catch Hook, n8n, Make, etc.).

    Args:
        url: The webhook URL to call.
        data: JSON data to send in the request body.
        method: HTTP method (default: POST).

    Returns:
        Dict with 'ok', 'status_code', and 'response'.
    """
    try:
        # SSRF protection: block private IPs
        from src.tools.browser import _is_url_safe
        ssrf_check = _is_url_safe(url)
        if ssrf_check:
            return {"ok": False, "error": ssrf_check}

        with httpx.Client(timeout=30) as client:
            if method.upper() == "GET":
                response = client.get(url)
            else:
                response = client.post(url, json=data or {})
            response.raise_for_status()

        # Try to parse JSON response
        try:
            result = response.json()
        except Exception:
            result = response.text[:2000]

        return {"ok": True, "status_code": response.status_code, "response": result}

    except httpx.TimeoutException:
        return {"ok": False, "error": f"Webhook timed out: {url}"}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def handle_bridge_request(request: dict[str, Any]) -> dict[str, Any]:
    """Handle an inbound webhook bridge request from Zapier/n8n.

    Expected payload:
        {
            "agent": "research_assistant",
            "task": "find the latest AI news",
            "api_key": "optional-pagal-api-token"
        }

    Returns:
        Dict with agent result.
    """
    try:
        agent_name = request.get("agent", "")
        task = request.get("task", "")

        if not agent_name or not task:
            return {"ok": False, "error": "Missing 'agent' or 'task' in request"}

        from src.core.runtime import load_agent, run_agent

        agent = load_agent(agent_name)
        result = run_agent(agent, task)

        return {
            "ok": result.ok,
            "output": result.output if result.ok else "",
            "error": result.error if not result.ok else "",
            "agent": agent_name,
            "tools_used": result.tools_used,
            "duration_seconds": result.duration_seconds,
        }

    except FileNotFoundError:
        return {"ok": False, "error": f"Agent '{request.get('agent', '')}' not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Register as a tool so agents can call external webhooks
register_tool(
    name="call_webhook",
    function=call_webhook,
    description="Call an external webhook URL (Zapier, n8n, Make, etc.) to trigger actions in other apps. Send JSON data and get the response.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The webhook URL to call"},
            "data": {"type": "object", "description": "JSON data to send in the request body"},
            "method": {"type": "string", "description": "HTTP method (POST or GET)", "default": "POST"},
        },
        "required": ["url"],
    },
)
