"""Natural Language Workflow Builder — describe automations in plain English.

Instead of YAML or drag-and-drop, users say:
  "When I get an email from a client, summarize it and add a task to my todo list"
  "Every morning at 8am, check the weather and send me a briefing on Telegram"
  "If competitor changes their pricing page, alert me on WhatsApp"

The system parses this into: agent config + trigger + delivery.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")


def parse_workflow_description(description: str) -> dict[str, Any]:
    """Parse a natural language workflow description into structured components.

    Uses the LLM to understand the user's intent and extract:
      - trigger: what starts the workflow (schedule, webhook, email, etc.)
      - agent: what agent should run (or create a new one)
      - task: what the agent should do
      - delivery: how to deliver the result (email, telegram, file, etc.)

    Args:
        description: Natural language workflow description.

    Returns:
        Dict with parsed components.
    """
    try:
        from src.core.llm import call_llm

        parse_prompt = f"""You are a workflow parser. Extract the structured components from this natural language automation description.

Description: "{description}"

Return a JSON object with these fields:
- "trigger_type": one of "schedule", "webhook", "email_received", "manual", "condition"
- "schedule": if trigger is schedule, the timing (e.g. "every 1h", "daily at 09:00"). Empty if not scheduled.
- "agent_name": a snake_case name for the agent (e.g. "email_summarizer", "price_checker")
- "agent_description": one-line description of what the agent does
- "agent_tools": list of tools needed (from: search_web, browse_url, read_file, write_file, run_shell, send_email, read_emails, query_documents, create_calendar_event, trigger_ifttt, control_smart_home, call_webhook, run_python)
- "agent_personality": how the agent should behave (2-3 sentences)
- "task": the specific task/prompt for each run
- "delivery_type": one of "email", "telegram", "whatsapp", "file", "notification", "none"
- "delivery_target": email address, phone number, file path, etc. (empty if unknown)

Return ONLY valid JSON, no other text."""

        result = call_llm(
            messages=[{"role": "user", "content": parse_prompt}],
            model="nvidia/nemotron-3-super-120b-a12b:free",
            timeout=30,
        )

        if not result["ok"]:
            return {"ok": False, "error": f"Failed to parse: {result['error']}"}

        content = result["content"].strip()
        # Extract JSON from code blocks if present
        if "```" in content:
            import re
            match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
            if match:
                content = match.group(1)

        parsed = json.loads(content)
        parsed["ok"] = True
        parsed["original_description"] = description
        return parsed

    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Failed to parse LLM output as JSON: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def build_workflow(description: str) -> dict[str, Any]:
    """Full pipeline: parse description → create agent → set up trigger → configure delivery.

    Args:
        description: Natural language workflow description.

    Returns:
        Dict with 'ok', created agent name, and workflow details.
    """
    # Step 1: Parse the description
    parsed = parse_workflow_description(description)
    if not parsed.get("ok"):
        return parsed

    results: dict[str, Any] = {"ok": True, "parsed": parsed, "actions": []}

    # Step 2: Create the agent
    try:
        import yaml

        from src.core.config import get_config
        config = get_config()

        agent_name = parsed.get("agent_name", "custom_workflow")
        agent_config = {
            "name": agent_name,
            "description": parsed.get("agent_description", description[:100]),
            "model": config.default_model,
            "tools": parsed.get("agent_tools", []),
            "personality": parsed.get("agent_personality", "You are a helpful automation assistant."),
            "memory": True,
        }

        agent_path = config.agents_dir / f"{agent_name}.yaml"
        if not agent_path.exists():
            agent_path.write_text(yaml.dump(agent_config, default_flow_style=False, sort_keys=False))
            results["actions"].append(f"Created agent: {agent_name}")
        else:
            results["actions"].append(f"Agent '{agent_name}' already exists (reusing)")

        results["agent_name"] = agent_name
        results["task"] = parsed.get("task", description)

    except Exception as e:
        results["actions"].append(f"Agent creation failed: {e}")

    # Step 3: Set up trigger
    trigger_type = parsed.get("trigger_type", "manual")
    schedule = parsed.get("schedule", "")

    if trigger_type == "schedule" and schedule:
        try:
            from src.core.hands import start_hand
            hand_result = start_hand(agent_name, schedule, parsed.get("task", description))
            if isinstance(hand_result, dict) and hand_result.get("ok"):
                results["actions"].append(f"Scheduled: {schedule}")
            else:
                results["actions"].append(f"Scheduling attempted: {schedule}")
        except Exception as e:
            results["actions"].append(f"Scheduling failed: {e}")
    elif trigger_type in ("webhook", "email_received"):
        results["actions"].append(f"Trigger type '{trigger_type}' — use the webhook bridge API to connect")

    # Step 4: Configure delivery
    delivery_type = parsed.get("delivery_type", "none")
    if delivery_type == "email":
        results["delivery"] = {"type": "email", "note": "Set EMAIL_* env vars. Agent can use send_email tool."}
    elif delivery_type == "telegram":
        results["delivery"] = {"type": "telegram", "note": "Use /use command in Telegram to route to this agent."}
    elif delivery_type == "whatsapp":
        results["delivery"] = {"type": "whatsapp", "note": "Set WHATSAPP_* env vars. Messages will be routed."}
    elif delivery_type == "file":
        results["delivery"] = {"type": "file", "path": parsed.get("delivery_target", "~/.pagal-os/workflow_output.md")}
    else:
        results["delivery"] = {"type": "none"}

    results["actions"].append(f"Delivery: {delivery_type}")
    results["summary"] = (
        f"Workflow '{agent_name}' created. "
        f"Trigger: {trigger_type}{'(' + schedule + ')' if schedule else ''}. "
        f"Delivery: {delivery_type}."
    )

    logger.info("NL workflow built: %s", results["summary"])
    return results


def list_workflow_suggestions() -> list[dict[str, str]]:
    """Return example workflow descriptions users can try."""
    return [
        {"description": "Every morning at 8am, search for AI news and email me a summary", "category": "Research"},
        {"description": "When I receive an email, summarize it and add key actions to my todo list", "category": "Productivity"},
        {"description": "Every Friday, generate a weekly analytics report and save it as a PDF", "category": "Business"},
        {"description": "Monitor competitor.com for price changes and alert me on Telegram", "category": "Monitoring"},
        {"description": "Every day at 6pm, create a workout plan based on my fitness level", "category": "Personal"},
        {"description": "When I paste a meeting transcript, extract action items and create calendar events", "category": "Productivity"},
        {"description": "Every hour, check my email for urgent messages and notify me on WhatsApp", "category": "Communication"},
        {"description": "When a new blog post idea comes in, research the topic and write a draft", "category": "Writing"},
    ]
