"""Agent Analytics — track and visualize agent performance over time.

Records every agent run (success, duration, tokens, cost) to a SQLite
database and exposes query functions for dashboards and charts.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Database path
_PAGAL_DIR = Path.home() / ".pagal-os"
_DB_PATH = _PAGAL_DIR / "pagal.db"


def _get_connection() -> sqlite3.Connection:
    """Get a SQLite connection and ensure the schema exists.

    Returns:
        Active sqlite3.Connection with row_factory set.
    """
    _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            task TEXT,
            success INTEGER DEFAULT 1,
            duration_seconds REAL DEFAULT 0,
            tokens_used INTEGER DEFAULT 0,
            tools_used INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            error TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def record_run(
    agent_name: str,
    task: str,
    success: bool,
    duration: float,
    tokens: int,
    tools: int,
    cost: float,
    error: str = "",
) -> None:
    """Save a completed agent run to the analytics database.

    Args:
        agent_name: Name of the agent that ran.
        task: The task description.
        success: Whether the run succeeded.
        duration: Duration in seconds.
        tokens: Estimated tokens used.
        tools: Number of tool calls made.
        cost: Estimated cost in USD.
        error: Error message if the run failed.
    """
    try:
        conn = _get_connection()
        conn.execute(
            """
            INSERT INTO agent_runs
                (agent_name, task, success, duration_seconds, tokens_used,
                 tools_used, cost_usd, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_name,
                task[:500] if task else "",
                1 if success else 0,
                round(duration, 2),
                tokens,
                tools,
                round(cost, 6),
                error[:500] if error else "",
            ),
        )
        conn.commit()
        conn.close()
        logger.debug("Recorded analytics for agent '%s'", agent_name)
    except Exception as e:
        logger.error("Failed to record analytics: %s", e)


def get_agent_analytics(agent_name: str, days: int = 30) -> dict[str, Any]:
    """Get performance analytics for a specific agent.

    Args:
        agent_name: Name of the agent.
        days: Number of days to look back.

    Returns:
        Dict with total_runs, success_rate, avg_duration,
        total_tokens, total_cost, and runs_per_day.
    """
    try:
        conn = _get_connection()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        row = conn.execute(
            """
            SELECT
                COUNT(*) as total_runs,
                SUM(success) as successes,
                AVG(duration_seconds) as avg_duration,
                SUM(tokens_used) as total_tokens,
                SUM(tools_used) as total_tools,
                SUM(cost_usd) as total_cost
            FROM agent_runs
            WHERE agent_name = ? AND created_at >= ?
            """,
            (agent_name, cutoff),
        ).fetchone()

        conn.close()

        total_runs = row["total_runs"] or 0
        successes = row["successes"] or 0
        success_rate = (successes / total_runs * 100) if total_runs > 0 else 0.0
        runs_per_day = total_runs / max(days, 1)

        return {
            "agent_name": agent_name,
            "days": days,
            "total_runs": total_runs,
            "success_rate": round(success_rate, 1),
            "avg_duration": round(row["avg_duration"] or 0, 2),
            "total_tokens": row["total_tokens"] or 0,
            "total_tools": row["total_tools"] or 0,
            "total_cost": round(row["total_cost"] or 0, 6),
            "runs_per_day": round(runs_per_day, 1),
        }

    except Exception as e:
        logger.error("Failed to get analytics for '%s': %s", agent_name, e)
        return {
            "agent_name": agent_name,
            "days": days,
            "total_runs": 0,
            "success_rate": 0.0,
            "avg_duration": 0,
            "total_tokens": 0,
            "total_tools": 0,
            "total_cost": 0,
            "runs_per_day": 0,
        }


def get_all_analytics(days: int = 30) -> dict[str, Any]:
    """Get system-wide analytics across all agents.

    Args:
        days: Number of days to look back.

    Returns:
        Dict with total_runs, success_rate, total_tokens, total_cost,
        and per_agent breakdown.
    """
    try:
        conn = _get_connection()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # System totals
        totals = conn.execute(
            """
            SELECT
                COUNT(*) as total_runs,
                SUM(success) as successes,
                AVG(duration_seconds) as avg_duration,
                SUM(tokens_used) as total_tokens,
                SUM(tools_used) as total_tools,
                SUM(cost_usd) as total_cost
            FROM agent_runs
            WHERE created_at >= ?
            """,
            (cutoff,),
        ).fetchone()

        # Per-agent breakdown
        agents_rows = conn.execute(
            """
            SELECT
                agent_name,
                COUNT(*) as runs,
                SUM(success) as successes,
                AVG(duration_seconds) as avg_duration,
                SUM(tokens_used) as tokens,
                SUM(cost_usd) as cost
            FROM agent_runs
            WHERE created_at >= ?
            GROUP BY agent_name
            ORDER BY runs DESC
            """,
            (cutoff,),
        ).fetchall()

        conn.close()

        total_runs = totals["total_runs"] or 0
        successes = totals["successes"] or 0
        success_rate = (successes / total_runs * 100) if total_runs > 0 else 0.0

        agents = []
        for r in agents_rows:
            agent_runs = r["runs"] or 0
            agent_successes = r["successes"] or 0
            agents.append({
                "agent_name": r["agent_name"],
                "runs": agent_runs,
                "success_rate": round(
                    (agent_successes / agent_runs * 100) if agent_runs > 0 else 0, 1,
                ),
                "avg_duration": round(r["avg_duration"] or 0, 2),
                "tokens": r["tokens"] or 0,
                "cost": round(r["cost"] or 0, 6),
            })

        return {
            "days": days,
            "total_runs": total_runs,
            "success_rate": round(success_rate, 1),
            "avg_duration": round(totals["avg_duration"] or 0, 2),
            "total_tokens": totals["total_tokens"] or 0,
            "total_tools": totals["total_tools"] or 0,
            "total_cost": round(totals["total_cost"] or 0, 6),
            "agents": agents,
        }

    except Exception as e:
        logger.error("Failed to get all analytics: %s", e)
        return {
            "days": days,
            "total_runs": 0,
            "success_rate": 0.0,
            "avg_duration": 0,
            "total_tokens": 0,
            "total_tools": 0,
            "total_cost": 0,
            "agents": [],
        }


def get_trend(agent_name: str, metric: str = "success_rate", days: int = 30) -> list[dict[str, Any]]:
    """Get daily values of a metric for charting.

    Args:
        agent_name: Name of the agent.
        metric: One of "success_rate", "runs", "tokens", "cost", "duration".
        days: Number of days to look back.

    Returns:
        List of dicts with "date" and "value" keys, one per day.
    """
    try:
        conn = _get_connection()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        rows = conn.execute(
            """
            SELECT
                DATE(created_at) as day,
                COUNT(*) as runs,
                SUM(success) as successes,
                AVG(duration_seconds) as avg_duration,
                SUM(tokens_used) as tokens,
                SUM(cost_usd) as cost
            FROM agent_runs
            WHERE agent_name = ? AND created_at >= ?
            GROUP BY DATE(created_at)
            ORDER BY day ASC
            """,
            (agent_name, cutoff),
        ).fetchall()

        conn.close()

        trend: list[dict[str, Any]] = []
        for r in rows:
            day_runs = r["runs"] or 0
            day_successes = r["successes"] or 0

            if metric == "success_rate":
                value = (day_successes / day_runs * 100) if day_runs > 0 else 0
            elif metric == "runs":
                value = day_runs
            elif metric == "tokens":
                value = r["tokens"] or 0
            elif metric == "cost":
                value = round(r["cost"] or 0, 6)
            elif metric == "duration":
                value = round(r["avg_duration"] or 0, 2)
            else:
                value = day_runs

            trend.append({
                "date": r["day"],
                "value": round(value, 2),
            })

        return trend

    except Exception as e:
        logger.error("Failed to get trend for '%s': %s", agent_name, e)
        return []


def get_top_agents(metric: str = "success_rate", limit: int = 5) -> list[dict[str, Any]]:
    """Get the best performing agents ranked by a metric.

    Args:
        metric: Ranking metric — "success_rate", "runs", "tokens", "cost".
        limit: Max number of agents to return.

    Returns:
        List of dicts with agent_name and metric value, sorted descending.
    """
    try:
        conn = _get_connection()

        if metric == "success_rate":
            order_col = "CAST(SUM(success) AS REAL) / COUNT(*) * 100"
        elif metric == "runs":
            order_col = "COUNT(*)"
        elif metric == "tokens":
            order_col = "SUM(tokens_used)"
        elif metric == "cost":
            order_col = "SUM(cost_usd)"
        else:
            order_col = "COUNT(*)"

        rows = conn.execute(
            f"""
            SELECT
                agent_name,
                COUNT(*) as runs,
                SUM(success) as successes,
                SUM(tokens_used) as tokens,
                SUM(cost_usd) as cost,
                {order_col} as rank_value
            FROM agent_runs
            GROUP BY agent_name
            HAVING COUNT(*) >= 1
            ORDER BY rank_value DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        conn.close()

        results: list[dict[str, Any]] = []
        for r in rows:
            agent_runs = r["runs"] or 0
            agent_successes = r["successes"] or 0
            results.append({
                "agent_name": r["agent_name"],
                "runs": agent_runs,
                "success_rate": round(
                    (agent_successes / agent_runs * 100) if agent_runs > 0 else 0, 1,
                ),
                "tokens": r["tokens"] or 0,
                "cost": round(r["cost"] or 0, 6),
                "rank_value": round(r["rank_value"] or 0, 2),
            })

        return results

    except Exception as e:
        logger.error("Failed to get top agents: %s", e)
        return []
