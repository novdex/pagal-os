"""PAGAL OS Rate Limiter — control LLM calls per agent per time window.

Uses an in-memory sliding window to track call timestamps per agent.
Before each LLM call, ``check_rate_limit()`` determines whether the
agent has exceeded its per-minute or per-hour quota. If so, callers
should wait ``retry_after_seconds`` before retrying.

Limits can be configured per-agent in their YAML under ``rate_limit:``.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("pagal_os")


@dataclass
class RateLimit:
    """Rate limit configuration and sliding window for a single agent.

    Attributes:
        agent_name: Name of the agent.
        max_calls_per_minute: Maximum LLM calls allowed per 60-second window.
        max_calls_per_hour: Maximum LLM calls allowed per 3600-second window.
        window: List of call timestamps (epoch floats).
    """

    agent_name: str
    max_calls_per_minute: int = 30
    max_calls_per_hour: int = 500
    window: list[float] = field(default_factory=list)


# Global store: agent_name -> RateLimit
_rate_limits: dict[str, RateLimit] = {}

# System-wide defaults
_DEFAULT_PER_MINUTE = 30
_DEFAULT_PER_HOUR = 500


def _get_or_create(agent_name: str) -> RateLimit:
    """Get the RateLimit for an agent, creating with defaults if needed.

    Args:
        agent_name: Name of the agent.

    Returns:
        The RateLimit instance for this agent.
    """
    if agent_name not in _rate_limits:
        # Try to load limits from agent YAML
        per_minute = _DEFAULT_PER_MINUTE
        per_hour = _DEFAULT_PER_HOUR
        try:
            from src.core.config import get_config

            import yaml

            config = get_config()
            agent_path = config.agents_dir / f"{agent_name}.yaml"
            if agent_path.exists():
                with open(agent_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                rl_config = data.get("rate_limit", {})
                if isinstance(rl_config, dict):
                    per_minute = rl_config.get("per_minute", per_minute)
                    per_hour = rl_config.get("per_hour", per_hour)
        except Exception:
            pass

        _rate_limits[agent_name] = RateLimit(
            agent_name=agent_name,
            max_calls_per_minute=per_minute,
            max_calls_per_hour=per_hour,
        )

    return _rate_limits[agent_name]


def _clean_window(rl: RateLimit) -> None:
    """Remove timestamps older than 1 hour from the sliding window.

    Args:
        rl: The RateLimit instance to clean.
    """
    cutoff = time.time() - 3600  # 1 hour ago
    rl.window = [ts for ts in rl.window if ts > cutoff]


def check_rate_limit(agent_name: str) -> dict[str, Any]:
    """Check whether an agent is allowed to make an LLM call right now.

    Cleans old timestamps, counts calls in the last minute and hour,
    and compares against the configured limits.

    Args:
        agent_name: Name of the agent to check.

    Returns:
        Dict with keys:
            - allowed: bool — True if the call is permitted.
            - calls_this_minute: int — calls in the last 60 seconds.
            - calls_this_hour: int — calls in the last 3600 seconds.
            - retry_after_seconds: int — seconds to wait if not allowed (0 if allowed).
    """
    rl = _get_or_create(agent_name)
    _clean_window(rl)

    now = time.time()
    minute_ago = now - 60
    hour_ago = now - 3600

    calls_minute = sum(1 for ts in rl.window if ts > minute_ago)
    calls_hour = len(rl.window)  # already cleaned to 1-hour window

    allowed = True
    retry_after = 0

    if calls_minute >= rl.max_calls_per_minute:
        allowed = False
        # Earliest call in the minute window will expire soonest
        oldest_in_minute = min(
            (ts for ts in rl.window if ts > minute_ago), default=now,
        )
        retry_after = max(int(oldest_in_minute - minute_ago) + 1, 1)
    elif calls_hour >= rl.max_calls_per_hour:
        allowed = False
        oldest_in_hour = min(rl.window, default=now)
        retry_after = max(int(oldest_in_hour - hour_ago) + 1, 1)

    return {
        "allowed": allowed,
        "calls_this_minute": calls_minute,
        "calls_this_hour": calls_hour,
        "retry_after_seconds": retry_after,
    }


def record_call(agent_name: str) -> None:
    """Record a new LLM call timestamp for an agent.

    Args:
        agent_name: Name of the agent that made the call.
    """
    rl = _get_or_create(agent_name)
    rl.window.append(time.time())


def get_rate_limits(agent_name: str | None = None) -> dict[str, Any]:
    """Get current rate limit config and usage for one or all agents.

    Args:
        agent_name: Specific agent name, or None for all agents.

    Returns:
        Dict with agent rate limit details. If agent_name is None,
        returns a dict mapping agent names to their details.
    """
    if agent_name:
        rl = _get_or_create(agent_name)
        _clean_window(rl)
        now = time.time()
        minute_ago = now - 60
        return {
            "agent_name": rl.agent_name,
            "max_calls_per_minute": rl.max_calls_per_minute,
            "max_calls_per_hour": rl.max_calls_per_hour,
            "calls_this_minute": sum(1 for ts in rl.window if ts > minute_ago),
            "calls_this_hour": len(rl.window),
        }

    result: dict[str, Any] = {}
    for name, rl in _rate_limits.items():
        _clean_window(rl)
        now = time.time()
        minute_ago = now - 60
        result[name] = {
            "agent_name": rl.agent_name,
            "max_calls_per_minute": rl.max_calls_per_minute,
            "max_calls_per_hour": rl.max_calls_per_hour,
            "calls_this_minute": sum(1 for ts in rl.window if ts > minute_ago),
            "calls_this_hour": len(rl.window),
        }
    return result


def set_rate_limit(
    agent_name: str,
    per_minute: int = 30,
    per_hour: int = 500,
) -> None:
    """Set custom rate limits for an agent.

    Args:
        agent_name: Name of the agent.
        per_minute: Maximum calls per minute.
        per_hour: Maximum calls per hour.
    """
    rl = _get_or_create(agent_name)
    rl.max_calls_per_minute = per_minute
    rl.max_calls_per_hour = per_hour
    logger.info(
        "Rate limit set for '%s': %d/min, %d/hr",
        agent_name, per_minute, per_hour,
    )


def get_rate_stats() -> dict[str, Any]:
    """Get system-wide rate limiting statistics.

    Returns:
        Dict with total_calls, busiest_agent, and avg calls per minute
        across all tracked agents.
    """
    now = time.time()
    minute_ago = now - 60

    total_calls = 0
    busiest_agent = ""
    busiest_count = 0
    agents_active = 0

    for name, rl in _rate_limits.items():
        _clean_window(rl)
        calls = len(rl.window)
        calls_minute = sum(1 for ts in rl.window if ts > minute_ago)
        total_calls += calls
        if calls_minute > busiest_count:
            busiest_count = calls_minute
            busiest_agent = name
        if calls > 0:
            agents_active += 1

    avg_per_minute = round(total_calls / max(agents_active, 1) / 60, 2)

    return {
        "total_calls_last_hour": total_calls,
        "busiest_agent": busiest_agent,
        "busiest_agent_calls_per_minute": busiest_count,
        "agents_tracked": len(_rate_limits),
        "agents_active": agents_active,
        "avg_calls_per_minute": avg_per_minute,
    }
