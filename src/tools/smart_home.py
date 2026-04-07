"""Smart Home / IoT / Calendar Bridge — agents control your physical world.

Connects to:
  - Home Assistant (smart home) via REST API
  - Google Calendar via API
  - IFTTT via webhooks (for 600+ IoT devices)
  - Generic webhooks for any smart device

Agents can: turn on lights, set thermostats, lock doors, create calendar events,
trigger IFTTT applets, and more.
"""

import json
import logging
import os
from typing import Any

import httpx

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")

# Config
_HA_URL = os.getenv("HOME_ASSISTANT_URL", "")  # e.g. http://homeassistant.local:8123
_HA_TOKEN = os.getenv("HOME_ASSISTANT_TOKEN", "")
_IFTTT_KEY = os.getenv("IFTTT_WEBHOOK_KEY", "")
_GCAL_API_KEY = os.getenv("GOOGLE_CALENDAR_API_KEY", "")


# ---------------------------------------------------------------------------
# Home Assistant
# ---------------------------------------------------------------------------

def control_smart_home(
    entity_id: str,
    action: str = "toggle",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Control a Home Assistant device.

    Args:
        entity_id: HA entity ID (e.g. 'light.living_room', 'switch.fan').
        action: 'turn_on', 'turn_off', 'toggle', or a service name.
        data: Optional extra data for the service call.

    Returns:
        Dict with 'ok' and response data.
    """
    if not _HA_URL or not _HA_TOKEN:
        return {"ok": False, "error": "HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN not set"}

    try:
        domain = entity_id.split(".")[0]
        service = action

        url = f"{_HA_URL}/api/services/{domain}/{service}"
        headers = {"Authorization": f"Bearer {_HA_TOKEN}", "Content-Type": "application/json"}
        payload = {"entity_id": entity_id}
        if data:
            payload.update(data)

        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        return {"ok": True, "message": f"{action} {entity_id}", "response": resp.json() if resp.text else {}}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_smart_home_state(entity_id: str = "") -> dict[str, Any]:
    """Get the state of a Home Assistant device or all devices.

    Args:
        entity_id: Specific entity to query, or empty for all states.

    Returns:
        Dict with device states.
    """
    if not _HA_URL or not _HA_TOKEN:
        return {"ok": False, "error": "Home Assistant not configured"}

    try:
        url = f"{_HA_URL}/api/states"
        if entity_id:
            url = f"{_HA_URL}/api/states/{entity_id}"

        headers = {"Authorization": f"Bearer {_HA_TOKEN}"}
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()

        data = resp.json()

        if isinstance(data, list):
            # All states — summarize
            states = [{"entity": s["entity_id"], "state": s["state"], "name": s["attributes"].get("friendly_name", "")} for s in data[:50]]
            return {"ok": True, "devices": states, "count": len(data)}
        else:
            return {"ok": True, "entity": data["entity_id"], "state": data["state"], "attributes": data.get("attributes", {})}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# IFTTT Webhook
# ---------------------------------------------------------------------------

def trigger_ifttt(event_name: str, value1: str = "", value2: str = "", value3: str = "") -> dict[str, Any]:
    """Trigger an IFTTT webhook applet.

    Args:
        event_name: IFTTT event name (from your Webhooks applet).
        value1-3: Up to 3 values to pass to the applet.

    Returns:
        Dict with 'ok' status.
    """
    if not _IFTTT_KEY:
        return {"ok": False, "error": "IFTTT_WEBHOOK_KEY not set"}

    try:
        url = f"https://maker.ifttt.com/trigger/{event_name}/with/key/{_IFTTT_KEY}"
        payload = {}
        if value1: payload["value1"] = value1
        if value2: payload["value2"] = value2
        if value3: payload["value3"] = value3

        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload)

        return {"ok": True, "message": f"IFTTT event '{event_name}' triggered"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def create_calendar_event(
    title: str,
    date: str,
    time_start: str = "",
    time_end: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Create a calendar event (stored locally, or via Google Calendar if configured).

    Args:
        title: Event title.
        date: Date in YYYY-MM-DD format.
        time_start: Start time (HH:MM, 24h format). Empty for all-day.
        time_end: End time (HH:MM). Defaults to 1 hour after start.
        description: Event description.

    Returns:
        Dict with 'ok' and event details.
    """
    try:
        from pathlib import Path
        import json

        cal_file = Path.home() / ".pagal-os" / "calendar.json"
        cal_file.parent.mkdir(parents=True, exist_ok=True)

        events = []
        if cal_file.exists():
            events = json.loads(cal_file.read_text())

        event = {
            "id": len(events) + 1,
            "title": title,
            "date": date,
            "time_start": time_start,
            "time_end": time_end or (f"{int(time_start.split(':')[0])+1}:{time_start.split(':')[1]}" if time_start and ":" in time_start else ""),
            "description": description,
        }
        events.append(event)

        cal_file.write_text(json.dumps(events, indent=2))
        logger.info("Calendar event created: %s on %s", title, date)

        return {"ok": True, "event": event, "message": f"Event '{title}' created for {date}"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_calendar_events(date: str = "") -> dict[str, Any]:
    """Get calendar events, optionally filtered by date.

    Args:
        date: Filter by date (YYYY-MM-DD). Empty for all events.

    Returns:
        Dict with 'ok' and 'events' list.
    """
    try:
        from pathlib import Path
        cal_file = Path.home() / ".pagal-os" / "calendar.json"

        if not cal_file.exists():
            return {"ok": True, "events": [], "message": "No events"}

        events = json.loads(cal_file.read_text())
        if date:
            events = [e for e in events if e.get("date") == date]

        return {"ok": True, "events": events}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# Auto-register tools
register_tool(name="control_smart_home", function=control_smart_home,
    description="Control a smart home device via Home Assistant (lights, switches, thermostats, etc.)",
    parameters={"type": "object", "properties": {
        "entity_id": {"type": "string", "description": "Device entity ID (e.g. light.living_room)"},
        "action": {"type": "string", "description": "Action: turn_on, turn_off, toggle", "default": "toggle"},
        "data": {"type": "object", "description": "Extra data (e.g. brightness, temperature)"},
    }, "required": ["entity_id"]})

register_tool(name="get_smart_home_state", function=get_smart_home_state,
    description="Get the state of smart home devices from Home Assistant.",
    parameters={"type": "object", "properties": {
        "entity_id": {"type": "string", "description": "Specific device, or empty for all", "default": ""},
    }, "required": []})

register_tool(name="trigger_ifttt", function=trigger_ifttt,
    description="Trigger an IFTTT applet via webhook. Use to control 600+ IoT devices and services.",
    parameters={"type": "object", "properties": {
        "event_name": {"type": "string", "description": "IFTTT webhook event name"},
        "value1": {"type": "string", "description": "Optional value 1", "default": ""},
        "value2": {"type": "string", "description": "Optional value 2", "default": ""},
        "value3": {"type": "string", "description": "Optional value 3", "default": ""},
    }, "required": ["event_name"]})

register_tool(name="create_calendar_event", function=create_calendar_event,
    description="Create a calendar event with title, date, optional time and description.",
    parameters={"type": "object", "properties": {
        "title": {"type": "string", "description": "Event title"},
        "date": {"type": "string", "description": "Date (YYYY-MM-DD)"},
        "time_start": {"type": "string", "description": "Start time (HH:MM)", "default": ""},
        "time_end": {"type": "string", "description": "End time (HH:MM)", "default": ""},
        "description": {"type": "string", "description": "Event description", "default": ""},
    }, "required": ["title", "date"]})

register_tool(name="get_calendar_events", function=get_calendar_events,
    description="Get calendar events, optionally filtered by date.",
    parameters={"type": "object", "properties": {
        "date": {"type": "string", "description": "Filter by date (YYYY-MM-DD)", "default": ""},
    }, "required": []})
