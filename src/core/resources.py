"""Resource management -- control agent usage limits.

Tracks and enforces per-agent resource limits including tokens, tool calls,
execution duration, and cost. Prevents runaway agents from consuming
excessive resources.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config

logger = logging.getLogger("pagal_os")


@dataclass
class ResourceLimits:
    """Per-agent resource limits and usage counters.

    Attributes:
        max_tokens: Maximum tokens per run.
        max_tool_calls: Maximum tool invocations per run.
        max_duration_seconds: Maximum runtime in seconds.
        max_cost_usd: Maximum cost per run in USD.
        tokens_used: Tokens consumed so far in the current run.
        tool_calls_used: Tool calls made so far in the current run.
        cost_used: Cost incurred so far in the current run.
        start_time: When the current run started (epoch seconds).
    """

    max_tokens: int = 10000
    max_tool_calls: int = 20
    max_duration_seconds: int = 300
    max_cost_usd: float = 0.10
    tokens_used: int = 0
    tool_calls_used: int = 0
    cost_used: float = 0.0
    start_time: float = 0.0


# Global usage tracking: agent_name -> cumulative daily stats
_daily_usage: dict[str, dict[str, Any]] = {}

# Per-run limits: agent_name -> ResourceLimits (active during a run)
_active_limits: dict[str, ResourceLimits] = {}


def _get_usage_file() -> Path:
    """Get the path to the daily usage tracking file.

    Returns:
        Path to ~/.pagal-os/usage.json.
    """
    config = get_config()
    return config.base_dir / "usage.json"


def _load_daily_usage() -> None:
    """Load daily usage from disk into the global _daily_usage dict."""
    global _daily_usage
    usage_file = _get_usage_file()

    if not usage_file.exists():
        _daily_usage = {}
        return

    try:
        with open(usage_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Check if the data is from today
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data.get("date") == today:
            _daily_usage = data.get("agents", {})
        else:
            # Stale data from a previous day -- reset
            _daily_usage = {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load usage data: %s", e)
        _daily_usage = {}


def _save_daily_usage() -> None:
    """Persist daily usage to ~/.pagal-os/usage.json."""
    usage_file = _get_usage_file()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    data = {
        "date": today,
        "agents": _daily_usage,
    }

    try:
        usage_file.parent.mkdir(parents=True, exist_ok=True)
        with open(usage_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error("Failed to save usage data: %s", e)


def get_limits(agent_name: str) -> ResourceLimits:
    """Load resource limits for an agent from its YAML config.

    Falls back to defaults if the agent YAML has no 'limits' section.

    Args:
        agent_name: Name of the agent.

    Returns:
        ResourceLimits instance with limits from config or defaults.
    """
    config = get_config()
    agent_path = config.agents_dir / f"{agent_name}.yaml"

    limits = ResourceLimits()

    if agent_path.exists():
        try:
            with open(agent_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            limits_data = data.get("limits", {})
            if isinstance(limits_data, dict):
                limits.max_tokens = limits_data.get("max_tokens", limits.max_tokens)
                limits.max_tool_calls = limits_data.get("max_tool_calls", limits.max_tool_calls)
                limits.max_duration_seconds = limits_data.get(
                    "max_duration_seconds", limits.max_duration_seconds,
                )
                limits.max_cost_usd = limits_data.get("max_cost_usd", limits.max_cost_usd)
        except Exception as e:
            logger.warning("Failed to read limits for agent '%s': %s", agent_name, e)

    return limits


def start_tracking(agent_name: str) -> ResourceLimits:
    """Begin resource tracking for an agent run.

    Creates a fresh ResourceLimits instance with counters at zero
    and registers it for the active run.

    Args:
        agent_name: Name of the agent starting a run.

    Returns:
        The ResourceLimits instance being tracked.
    """
    limits = get_limits(agent_name)
    limits.tokens_used = 0
    limits.tool_calls_used = 0
    limits.cost_used = 0.0
    limits.start_time = time.time()

    _active_limits[agent_name] = limits
    return limits


def stop_tracking(agent_name: str) -> None:
    """Stop resource tracking for an agent run and update daily totals.

    Args:
        agent_name: Name of the agent whose run has ended.
    """
    limits = _active_limits.pop(agent_name, None)
    if limits is None:
        return

    # Accumulate into daily usage
    if not _daily_usage:
        _load_daily_usage()

    if agent_name not in _daily_usage:
        _daily_usage[agent_name] = {
            "total_tokens": 0,
            "total_tool_calls": 0,
            "total_cost_usd": 0.0,
            "total_runs": 0,
            "total_duration_seconds": 0.0,
        }

    entry = _daily_usage[agent_name]
    entry["total_tokens"] += limits.tokens_used
    entry["total_tool_calls"] += limits.tool_calls_used
    entry["total_cost_usd"] += limits.cost_used
    entry["total_runs"] += 1
    entry["total_duration_seconds"] += time.time() - limits.start_time

    _save_daily_usage()


def check_limit(limits: ResourceLimits, resource: str) -> bool:
    """Check whether a specific resource is still under its limit.

    Args:
        limits: The ResourceLimits instance to check.
        resource: Which resource to check. One of:
            'tokens', 'tool_calls', 'duration', 'cost'.

    Returns:
        True if the resource is under the limit, False if exceeded.
    """
    if resource == "tokens":
        return limits.tokens_used < limits.max_tokens
    elif resource == "tool_calls":
        return limits.tool_calls_used < limits.max_tool_calls
    elif resource == "duration":
        elapsed = time.time() - limits.start_time if limits.start_time else 0
        return elapsed < limits.max_duration_seconds
    elif resource == "cost":
        return limits.cost_used < limits.max_cost_usd
    else:
        logger.warning("Unknown resource type: '%s'", resource)
        return True


def check_all_limits(limits: ResourceLimits) -> str | None:
    """Check all resource limits at once.

    Args:
        limits: The ResourceLimits instance to check.

    Returns:
        None if all limits are OK, or a string describing which limit was exceeded.
    """
    if not check_limit(limits, "tokens"):
        return f"Token limit exceeded ({limits.tokens_used}/{limits.max_tokens})"
    if not check_limit(limits, "tool_calls"):
        return f"Tool call limit exceeded ({limits.tool_calls_used}/{limits.max_tool_calls})"
    if not check_limit(limits, "duration"):
        elapsed = time.time() - limits.start_time
        return f"Duration limit exceeded ({elapsed:.0f}s/{limits.max_duration_seconds}s)"
    if not check_limit(limits, "cost"):
        return f"Cost limit exceeded (${limits.cost_used:.4f}/${limits.max_cost_usd:.4f})"
    return None


def track_usage(
    agent_name: str,
    tokens: int = 0,
    tool_calls: int = 0,
    cost: float = 0.0,
) -> None:
    """Increment usage counters for a running agent.

    Args:
        agent_name: Name of the agent.
        tokens: Number of tokens to add.
        tool_calls: Number of tool calls to add.
        cost: Cost in USD to add.
    """
    limits = _active_limits.get(agent_name)
    if limits is None:
        return

    limits.tokens_used += tokens
    limits.tool_calls_used += tool_calls
    limits.cost_used += cost


def get_usage_report(agent_name: str | None = None) -> dict[str, Any]:
    """Get usage statistics for one or all agents.

    Args:
        agent_name: Specific agent name, or None for all agents.

    Returns:
        Dict with usage data. If agent_name is specified, returns that agent's
        stats. Otherwise returns stats for all agents.
    """
    if not _daily_usage:
        _load_daily_usage()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if agent_name:
        agent_data = _daily_usage.get(agent_name, {
            "total_tokens": 0,
            "total_tool_calls": 0,
            "total_cost_usd": 0.0,
            "total_runs": 0,
            "total_duration_seconds": 0.0,
        })

        # Add active run info if currently running
        active = _active_limits.get(agent_name)
        currently_running = active is not None
        current_run = {}
        if active:
            current_run = {
                "tokens_used": active.tokens_used,
                "tool_calls_used": active.tool_calls_used,
                "cost_used": active.cost_used,
                "duration_seconds": time.time() - active.start_time,
                "limits": {
                    "max_tokens": active.max_tokens,
                    "max_tool_calls": active.max_tool_calls,
                    "max_duration_seconds": active.max_duration_seconds,
                    "max_cost_usd": active.max_cost_usd,
                },
            }

        return {
            "ok": True,
            "date": today,
            "agent": agent_name,
            "daily": agent_data,
            "currently_running": currently_running,
            "current_run": current_run,
        }

    # All agents
    all_agents = {}
    for name, data in _daily_usage.items():
        all_agents[name] = {
            **data,
            "currently_running": name in _active_limits,
        }

    return {
        "ok": True,
        "date": today,
        "agents": all_agents,
    }


def reset_daily_usage() -> None:
    """Reset all daily usage counters.

    Typically called at midnight by a scheduled task or on-demand.
    """
    global _daily_usage
    _daily_usage = {}
    _save_daily_usage()
    logger.info("Daily usage counters reset.")
