"""Agent Health Monitor — heartbeat, crash detection, auto-restart.

Tracks agent heartbeats, detects dead/degraded agents, and automatically
restarts scheduled Hands that have crashed. Runs a background monitor
thread that checks all agents every 60 seconds.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("pagal_os")

# Thresholds (in seconds)
_HEARTBEAT_DEAD_THRESHOLD = 300  # 5 minutes without heartbeat = dead
_HEARTBEAT_DEGRADED_THRESHOLD = 120  # 2 minutes = degraded
_MAX_AUTO_RESTARTS = 3
_MONITOR_INTERVAL = 60  # Check every 60 seconds

# In-memory heartbeat storage: agent_name -> {last_heartbeat, started_at, restart_count, errors}
_heartbeats: dict[str, dict[str, Any]] = {}
_heartbeats_lock = threading.Lock()

# Monitor thread reference
_monitor_thread: threading.Thread | None = None
_monitor_running = False


@dataclass
class AgentHealth:
    """Health status of a single agent.

    Attributes:
        agent_name: Name of the agent.
        status: Current status ('healthy', 'degraded', or 'dead').
        last_heartbeat: Unix timestamp of last heartbeat.
        uptime_seconds: Seconds since the agent started.
        restart_count: Number of times the agent has been auto-restarted.
        errors_last_hour: Number of errors in the last hour.
    """

    agent_name: str
    status: str  # "healthy", "degraded", "dead"
    last_heartbeat: float
    uptime_seconds: float
    restart_count: int
    errors_last_hour: int


def record_heartbeat(agent_name: str) -> None:
    """Record a heartbeat from an agent, indicating it is alive.

    Should be called periodically during agent execution (e.g. every 30s
    in the tool loop).

    Args:
        agent_name: The agent sending the heartbeat.
    """
    now = time.time()
    with _heartbeats_lock:
        if agent_name not in _heartbeats:
            _heartbeats[agent_name] = {
                "last_heartbeat": now,
                "started_at": now,
                "restart_count": 0,
                "errors": [],
            }
        else:
            _heartbeats[agent_name]["last_heartbeat"] = now


def record_error(agent_name: str) -> None:
    """Record an error for an agent (for errors_last_hour tracking).

    Args:
        agent_name: The agent that encountered an error.
    """
    now = time.time()
    with _heartbeats_lock:
        if agent_name not in _heartbeats:
            _heartbeats[agent_name] = {
                "last_heartbeat": now,
                "started_at": now,
                "restart_count": 0,
                "errors": [now],
            }
        else:
            _heartbeats[agent_name]["errors"].append(now)
            # Prune errors older than 1 hour
            cutoff = now - 3600
            _heartbeats[agent_name]["errors"] = [
                t for t in _heartbeats[agent_name]["errors"] if t > cutoff
            ]


def check_health(agent_name: str) -> AgentHealth:
    """Check the health status of a specific agent.

    Determines status based on time since last heartbeat:
    - healthy: heartbeat within 2 minutes
    - degraded: heartbeat between 2 and 5 minutes ago
    - dead: no heartbeat for 5+ minutes

    Args:
        agent_name: The agent to check.

    Returns:
        AgentHealth dataclass with current status and metrics.
    """
    now = time.time()
    with _heartbeats_lock:
        data = _heartbeats.get(agent_name)

    if not data:
        return AgentHealth(
            agent_name=agent_name,
            status="dead",
            last_heartbeat=0,
            uptime_seconds=0,
            restart_count=0,
            errors_last_hour=0,
        )

    elapsed = now - data["last_heartbeat"]
    if elapsed > _HEARTBEAT_DEAD_THRESHOLD:
        status = "dead"
    elif elapsed > _HEARTBEAT_DEGRADED_THRESHOLD:
        status = "degraded"
    else:
        status = "healthy"

    # Count errors in the last hour
    cutoff = now - 3600
    errors_last_hour = len([t for t in data.get("errors", []) if t > cutoff])

    return AgentHealth(
        agent_name=agent_name,
        status=status,
        last_heartbeat=data["last_heartbeat"],
        uptime_seconds=now - data["started_at"],
        restart_count=data.get("restart_count", 0),
        errors_last_hour=errors_last_hour,
    )


def check_all_health() -> list[AgentHealth]:
    """Check health of all known agents.

    Returns:
        List of AgentHealth objects for every agent that has ever sent a heartbeat.
    """
    with _heartbeats_lock:
        agent_names = list(_heartbeats.keys())
    return [check_health(name) for name in agent_names]


def auto_restart(agent_name: str) -> bool:
    """Auto-restart a dead agent if it was a scheduled Hand.

    Only restarts if the agent is dead and has not exceeded the maximum
    restart count (_MAX_AUTO_RESTARTS = 3).

    Args:
        agent_name: The agent to try restarting.

    Returns:
        True if the agent was restarted, False otherwise.
    """
    try:
        health = check_health(agent_name)
        if health.status != "dead":
            logger.debug("Agent '%s' is not dead (status=%s), skipping restart", agent_name, health.status)
            return False

        with _heartbeats_lock:
            data = _heartbeats.get(agent_name, {})
            restart_count = data.get("restart_count", 0)

        if restart_count >= _MAX_AUTO_RESTARTS:
            logger.warning(
                "Agent '%s' exceeded max restarts (%d/%d), not restarting",
                agent_name, restart_count, _MAX_AUTO_RESTARTS,
            )
            return False

        # Check if this agent is a Hand (scheduled agent)
        try:
            from src.core.hands import _active_hands, start_hand

            if agent_name not in _active_hands:
                logger.debug("Agent '%s' is not an active Hand, skipping restart", agent_name)
                return False

            hand_info = _active_hands[agent_name]
            schedule = hand_info.get("schedule", "every 1h")
            task = hand_info.get("task", "")

            if not task:
                logger.warning("Hand '%s' has no task, cannot restart", agent_name)
                return False

            # Restart the hand
            result = start_hand(agent_name, schedule, task)
            if result.get("ok"):
                with _heartbeats_lock:
                    if agent_name in _heartbeats:
                        _heartbeats[agent_name]["restart_count"] = restart_count + 1
                        _heartbeats[agent_name]["last_heartbeat"] = time.time()
                        _heartbeats[agent_name]["started_at"] = time.time()
                logger.info("Auto-restarted Hand '%s' (restart %d/%d)", agent_name, restart_count + 1, _MAX_AUTO_RESTARTS)
                return True
            else:
                logger.error("Failed to restart Hand '%s': %s", agent_name, result.get("error", "unknown"))
                return False

        except ImportError:
            logger.debug("Hands module not available, cannot restart '%s'", agent_name)
            return False

    except Exception as e:
        logger.error("Auto-restart failed for '%s': %s", agent_name, e)
        return False


def get_health_dashboard() -> dict[str, Any]:
    """Get system-wide health overview.

    Returns:
        Dict with total_agents, healthy, degraded, dead counts, and
        a list of all agent health statuses.
    """
    all_health = check_all_health()

    healthy = sum(1 for h in all_health if h.status == "healthy")
    degraded = sum(1 for h in all_health if h.status == "degraded")
    dead = sum(1 for h in all_health if h.status == "dead")

    agents_data = []
    for h in all_health:
        agents_data.append({
            "agent_name": h.agent_name,
            "status": h.status,
            "last_heartbeat": h.last_heartbeat,
            "uptime_seconds": round(h.uptime_seconds, 1),
            "restart_count": h.restart_count,
            "errors_last_hour": h.errors_last_hour,
        })

    return {
        "total_agents": len(all_health),
        "healthy": healthy,
        "degraded": degraded,
        "dead": dead,
        "agents": agents_data,
    }


def _monitor_loop() -> None:
    """Background monitor loop that checks all agents and auto-restarts dead Hands.

    Runs every _MONITOR_INTERVAL seconds in a daemon thread.
    """
    global _monitor_running

    logger.info("Health monitor started (interval=%ds)", _MONITOR_INTERVAL)
    while _monitor_running:
        try:
            all_health = check_all_health()
            for health in all_health:
                if health.status == "dead":
                    logger.info("Agent '%s' is dead, attempting auto-restart", health.agent_name)
                    auto_restart(health.agent_name)
                elif health.status == "degraded":
                    logger.debug("Agent '%s' is degraded (last heartbeat %.0fs ago)",
                                 health.agent_name, time.time() - health.last_heartbeat)
        except Exception as e:
            logger.error("Health monitor error: %s", e)

        # Sleep in small increments so we can stop quickly
        for _ in range(int(_MONITOR_INTERVAL)):
            if not _monitor_running:
                break
            time.sleep(1)

    logger.info("Health monitor stopped")


def start_health_monitor() -> None:
    """Start the background health monitor thread.

    The monitor checks all agents every 60 seconds and auto-restarts
    dead Hands. Runs as a daemon thread (won't block process exit).
    """
    global _monitor_thread, _monitor_running

    if _monitor_thread and _monitor_thread.is_alive():
        logger.debug("Health monitor already running")
        return

    _monitor_running = True
    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        daemon=True,
        name="health-monitor",
    )
    _monitor_thread.start()
    logger.info("Health monitor thread started")


def stop_health_monitor() -> None:
    """Stop the background health monitor thread."""
    global _monitor_running
    _monitor_running = False
    logger.info("Health monitor stop requested")
