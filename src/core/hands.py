"""Hands -- autonomous agents that run on schedules.

A Hand is an agent that runs automatically on a cron-like schedule.
Unlike regular agents that wait for user input, Hands work 24/7
building knowledge, monitoring targets, and reporting results.
"""

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import get_config

logger = logging.getLogger("pagal_os")

# Active hands: agent_name -> {thread, task, schedule, interval, stop_event, last_run, next_run}
_active_hands: dict[str, dict[str, Any]] = {}

# Lock for thread-safe access to _active_hands
_hands_lock = threading.Lock()


def _get_hands_file() -> Path:
    """Get the path to the hands persistence file.

    Returns:
        Path to ~/.pagal-os/hands.json.
    """
    config = get_config()
    return config.base_dir / "hands.json"


def _get_hands_log_dir() -> Path:
    """Get the directory for hand execution logs.

    Returns:
        Path to ~/.pagal-os/logs/hands/.
    """
    config = get_config()
    log_dir = config.logs_dir / "hands"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _parse_schedule(schedule: str) -> int:
    """Convert a human-readable schedule string to seconds.

    Supports formats:
        - "every 5m"    -> 300 seconds
        - "every 1h"    -> 3600 seconds
        - "every 24h"   -> 86400 seconds
        - "daily at 08:00" -> 86400 seconds (runs once per day)

    Args:
        schedule: Human-readable schedule string.

    Returns:
        Interval in seconds.

    Raises:
        ValueError: If the schedule string cannot be parsed.
    """
    schedule = schedule.strip().lower()

    # Match "every Xm" or "every Xh" or "every Xs"
    match = re.match(r"every\s+(\d+)\s*(s|m|h|d)", schedule)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return value * multipliers[unit]

    # Match "daily at HH:MM"
    match = re.match(r"daily\s+at\s+(\d{1,2}):(\d{2})", schedule)
    if match:
        # For daily schedules, we use 86400 seconds (24 hours) as the interval.
        # The _schedule_loop handles the initial delay to align with the target time.
        return 86400

    raise ValueError(
        f"Cannot parse schedule: '{schedule}'. "
        "Use formats like 'every 5m', 'every 1h', 'every 24h', or 'daily at 08:00'."
    )


def _calculate_initial_delay(schedule: str) -> float:
    """Calculate the delay before the first run for 'daily at HH:MM' schedules.

    For 'every X' schedules, returns 0 (run immediately).

    Args:
        schedule: The schedule string.

    Returns:
        Delay in seconds before the first execution.
    """
    schedule = schedule.strip().lower()
    match = re.match(r"daily\s+at\s+(\d{1,2}):(\d{2})", schedule)
    if not match:
        return 0.0

    target_hour = int(match.group(1))
    target_minute = int(match.group(2))
    now = datetime.now()
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

    if target <= now:
        # Already past today's target time -- schedule for tomorrow
        from datetime import timedelta
        target += timedelta(days=1)

    return (target - now).total_seconds()


def _schedule_loop(agent_name: str, interval_seconds: int, task: str, initial_delay: float = 0.0) -> None:
    """Background thread that runs an agent on a schedule.

    Saves output from each run to a log file under ~/.pagal-os/logs/hands/.

    Args:
        agent_name: Name of the agent to run.
        interval_seconds: Seconds between runs.
        task: The task string to pass to the agent each run.
        initial_delay: Seconds to wait before the first run.
    """
    from src.core.runtime import load_agent, run_agent

    with _hands_lock:
        hand_info = _active_hands.get(agent_name)
        if not hand_info:
            return
        stop_event: threading.Event = hand_info["stop_event"]

    log_dir = _get_hands_log_dir()
    log_file = log_dir / f"{agent_name}.log"

    # Wait for initial delay (for "daily at HH:MM" schedules)
    if initial_delay > 0:
        logger.info(
            "Hand '%s' waiting %.0f seconds before first run.",
            agent_name, initial_delay,
        )
        if stop_event.wait(timeout=initial_delay):
            logger.info("Hand '%s' stopped during initial delay.", agent_name)
            return

    while not stop_event.is_set():
        run_timestamp = datetime.now(timezone.utc).isoformat()

        with _hands_lock:
            if agent_name in _active_hands:
                _active_hands[agent_name]["last_run"] = run_timestamp

        logger.info("Hand '%s' executing task: %s", agent_name, task)

        try:
            agent = load_agent(agent_name)
            result = run_agent(agent, task)

            # Write log entry
            log_entry = {
                "timestamp": run_timestamp,
                "agent": agent_name,
                "task": task,
                "ok": result.ok,
                "output": result.output[:2000] if result.output else "",
                "error": result.error,
                "duration_seconds": result.duration_seconds,
                "tools_used": result.tools_used,
            }

            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry) + "\n")
            except Exception as log_err:
                logger.warning("Failed to write hand log for '%s': %s", agent_name, log_err)

            logger.info(
                "Hand '%s' completed run (ok=%s, duration=%.1fs).",
                agent_name, result.ok, result.duration_seconds,
            )

        except FileNotFoundError:
            logger.error("Hand '%s' agent not found. Stopping hand.", agent_name)
            with _hands_lock:
                if agent_name in _active_hands:
                    _active_hands[agent_name]["status"] = "error"
            break
        except Exception as e:
            logger.error("Hand '%s' run failed: %s", agent_name, e, exc_info=True)
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "timestamp": run_timestamp,
                        "agent": agent_name,
                        "task": task,
                        "ok": False,
                        "error": str(e),
                    }) + "\n")
            except Exception:
                pass

        # Update next_run
        next_run = datetime.now(timezone.utc).timestamp() + interval_seconds
        with _hands_lock:
            if agent_name in _active_hands:
                _active_hands[agent_name]["next_run"] = datetime.fromtimestamp(
                    next_run, tz=timezone.utc
                ).isoformat()

        # Wait for the next interval or until stopped
        if stop_event.wait(timeout=interval_seconds):
            logger.info("Hand '%s' stopped.", agent_name)
            break

    logger.info("Hand '%s' schedule loop ended.", agent_name)


def start_hand(agent_name: str, schedule: str, task: str) -> dict[str, Any]:
    """Start an agent running on a schedule.

    Args:
        agent_name: Name of the agent (must exist in ~/.pagal-os/agents/).
        schedule: Schedule string, e.g. "every 5m", "every 1h", "daily at 08:00".
        task: The task to execute on each run.

    Returns:
        Dict with status info: ok, agent, schedule, interval_seconds, message.
    """
    try:
        interval = _parse_schedule(schedule)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    # Verify agent exists
    try:
        from src.core.runtime import load_agent
        load_agent(agent_name)
    except FileNotFoundError:
        return {"ok": False, "error": f"Agent '{agent_name}' not found."}
    except Exception as e:
        return {"ok": False, "error": f"Failed to load agent '{agent_name}': {e}"}

    with _hands_lock:
        # Stop existing hand if running
        if agent_name in _active_hands:
            existing = _active_hands[agent_name]
            stop_evt = existing.get("stop_event")
            if stop_evt:
                stop_evt.set()

        stop_event = threading.Event()
        initial_delay = _calculate_initial_delay(schedule)

        now_iso = datetime.now(timezone.utc).isoformat()
        next_run_ts = datetime.now(timezone.utc).timestamp() + initial_delay
        next_run_iso = datetime.fromtimestamp(next_run_ts, tz=timezone.utc).isoformat()

        hand_info: dict[str, Any] = {
            "task": task,
            "schedule": schedule,
            "interval_seconds": interval,
            "stop_event": stop_event,
            "status": "running",
            "started_at": now_iso,
            "last_run": None,
            "next_run": next_run_iso,
        }

        thread = threading.Thread(
            target=_schedule_loop,
            args=(agent_name, interval, task, initial_delay),
            daemon=True,
            name=f"hand-{agent_name}",
        )
        hand_info["thread"] = thread
        _active_hands[agent_name] = hand_info

    thread.start()

    # Persist to disk
    _save_hands()

    logger.info(
        "Started hand '%s' with schedule '%s' (every %ds). Task: %s",
        agent_name, schedule, interval, task,
    )

    return {
        "ok": True,
        "agent": agent_name,
        "schedule": schedule,
        "interval_seconds": interval,
        "message": f"Hand '{agent_name}' started on schedule '{schedule}'.",
    }


def stop_hand(agent_name: str) -> bool:
    """Stop a scheduled hand.

    Args:
        agent_name: Name of the agent/hand to stop.

    Returns:
        True if the hand was found and stopped, False otherwise.
    """
    with _hands_lock:
        hand_info = _active_hands.pop(agent_name, None)

    if hand_info is None:
        return False

    stop_event = hand_info.get("stop_event")
    if stop_event:
        stop_event.set()

    _save_hands()
    logger.info("Stopped hand '%s'.", agent_name)
    return True


def list_hands() -> list[dict[str, Any]]:
    """Return all active hands with status information.

    Returns:
        List of dicts with agent name, schedule, task, status, last_run, next_run.
    """
    result = []
    with _hands_lock:
        for name, info in _active_hands.items():
            thread: threading.Thread | None = info.get("thread")
            is_alive = thread.is_alive() if thread else False
            result.append({
                "agent": name,
                "schedule": info.get("schedule", ""),
                "task": info.get("task", ""),
                "interval_seconds": info.get("interval_seconds", 0),
                "status": "running" if is_alive else info.get("status", "stopped"),
                "started_at": info.get("started_at"),
                "last_run": info.get("last_run"),
                "next_run": info.get("next_run"),
            })
    return result


def _save_hands() -> None:
    """Persist active hands to ~/.pagal-os/hands.json for restart recovery."""
    hands_file = _get_hands_file()
    data = []
    with _hands_lock:
        for name, info in _active_hands.items():
            data.append({
                "agent": name,
                "schedule": info.get("schedule", ""),
                "task": info.get("task", ""),
            })

    try:
        hands_file.parent.mkdir(parents=True, exist_ok=True)
        with open(hands_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug("Saved %d hands to %s", len(data), hands_file)
    except Exception as e:
        logger.error("Failed to save hands to %s: %s", hands_file, e)


def restore_hands() -> int:
    """Restore hands from ~/.pagal-os/hands.json on startup.

    Reads the persisted hands configuration and restarts all active hands.

    Returns:
        Number of hands successfully restored.
    """
    hands_file = _get_hands_file()
    if not hands_file.exists():
        return 0

    try:
        with open(hands_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read hands.json: %s", e)
        return 0

    if not isinstance(data, list):
        logger.warning("hands.json has unexpected format. Skipping restore.")
        return 0

    restored = 0
    for entry in data:
        agent_name = entry.get("agent", "")
        schedule = entry.get("schedule", "")
        task = entry.get("task", "")

        if not agent_name or not schedule or not task:
            logger.warning("Skipping invalid hand entry: %s", entry)
            continue

        result = start_hand(agent_name, schedule, task)
        if result.get("ok"):
            restored += 1
            logger.info("Restored hand '%s'.", agent_name)
        else:
            logger.warning("Failed to restore hand '%s': %s", agent_name, result.get("error"))

    logger.info("Restored %d/%d hands from disk.", restored, len(data))
    return restored
