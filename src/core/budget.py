"""Budget Governor -- control API costs per agent.

Hard dollar limits per agent, per day, per month. Agent stops when budget hits.
Uses SQLite table in pagal.db for persistent tracking.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("pagal_os")

# Cost per 1M tokens by model prefix
MODEL_COSTS: dict[str, float] = {
    "nvidia/nemotron": 0.0,  # free
    "xiaomi/mimo-v2-pro": 1.0,
    "openai/gpt-5.4-nano": 0.20,
    "ollama/": 0.0,  # local = free
    "default": 0.50,
}


@dataclass
class BudgetConfig:
    """Budget limits for a single agent.

    Attributes:
        daily_limit_usd: Maximum spend per day in USD.
        monthly_limit_usd: Maximum spend per month in USD.
        per_run_limit_usd: Maximum spend per single run in USD.
    """

    daily_limit_usd: float = 1.0
    monthly_limit_usd: float = 10.0
    per_run_limit_usd: float = 0.10


def _db_path() -> Path:
    """Return the path to the budget SQLite database.

    Returns:
        Path to ~/.pagal-os/pagal.db.
    """
    db_dir = Path.home() / ".pagal-os"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "pagal.db"


def _get_conn() -> sqlite3.Connection:
    """Open a connection to the budget database and ensure the table exists.

    Delegates to the central database module when available, falling
    back to a local connection if not.

    Returns:
        sqlite3.Connection with budget_tracking table ready.
    """
    _default = Path.home() / ".pagal-os" / "pagal.db"
    db = _db_path()
    conn = None
    if db == _default:
        try:
            from src.core.database import get_connection
            conn = get_connection()
        except Exception:
            pass
    if conn is None:
        conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budget_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            date TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            llm_calls INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def estimate_tokens(text: str) -> int:
    """Estimate token count from text. ~4 chars per token for English text.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count (minimum 1).
    """
    return max(1, len(text) // 4)


def calculate_cost(tokens: int, model: str) -> float:
    """Calculate cost based on model pricing.

    Matches the model identifier against MODEL_COSTS keys as prefixes,
    falling back to the 'default' rate.

    Args:
        tokens: Number of tokens.
        model: Full model identifier string.

    Returns:
        Cost in USD for the given token count.
    """
    cost_per_million = MODEL_COSTS.get(model, MODEL_COSTS["default"])
    for prefix, cost in MODEL_COSTS.items():
        if prefix == "default":
            continue
        if model.startswith(prefix):
            cost_per_million = cost
            break
    return (tokens / 1_000_000) * cost_per_million


def _cost_for_model(model: str) -> float:
    """Look up the per-1M-token cost for a given model identifier.

    Checks MODEL_COSTS keys as prefixes. Falls back to 'default'.

    Args:
        model: Full model identifier string.

    Returns:
        Cost in USD per 1 million tokens.
    """
    for prefix, cost in MODEL_COSTS.items():
        if prefix == "default":
            continue
        if model.startswith(prefix):
            return cost
    return MODEL_COSTS["default"]


def get_budget(agent_name: str) -> BudgetConfig:
    """Load budget configuration from agent YAML or return defaults.

    Reads the agent's YAML file from ~/.pagal-os/agents/{agent_name}.yaml
    and extracts the 'budget' section. Falls back to BudgetConfig defaults.

    Args:
        agent_name: Name of the agent.

    Returns:
        BudgetConfig with limits for this agent.
    """
    try:
        agent_path = Path.home() / ".pagal-os" / "agents" / f"{agent_name}.yaml"
        if agent_path.exists():
            with open(agent_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            budget_data = data.get("budget", {})
            if isinstance(budget_data, dict):
                return BudgetConfig(
                    daily_limit_usd=float(budget_data.get("daily_limit_usd", 1.0)),
                    monthly_limit_usd=float(budget_data.get("monthly_limit_usd", 10.0)),
                    per_run_limit_usd=float(budget_data.get("per_run_limit_usd", 0.10)),
                )
    except Exception as e:
        logger.debug("Failed to load budget config for '%s': %s", agent_name, e)

    return BudgetConfig()


def track_cost(
    agent_name: str,
    tokens: int,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    """Estimate and record cost for an LLM call.

    Calculates cost based on token count and model pricing, then inserts
    or updates the budget_tracking row for today. If input_tokens and
    output_tokens are provided, their sum is used instead of ``tokens``.

    Args:
        agent_name: Name of the agent incurring the cost.
        tokens: Total number of tokens (fallback if input/output not provided).
        model: Model identifier used for the call.
        input_tokens: Token count for the prompt/input.
        output_tokens: Token count for the response/output.

    Returns:
        The estimated cost in USD for this call.
    """
    try:
        # Prefer explicit input+output counts when available
        if input_tokens > 0 or output_tokens > 0:
            tokens = input_tokens + output_tokens

        cost_usd = calculate_cost(tokens, model)
        today = datetime.now().strftime("%Y-%m-%d")

        conn = _get_conn()
        try:
            # Check if row exists for today
            row = conn.execute(
                "SELECT id, tokens_used, cost_usd, llm_calls FROM budget_tracking "
                "WHERE agent_name = ? AND date = ?",
                (agent_name, today),
            ).fetchone()

            if row:
                conn.execute(
                    "UPDATE budget_tracking SET tokens_used = tokens_used + ?, "
                    "cost_usd = cost_usd + ?, llm_calls = llm_calls + 1 "
                    "WHERE id = ?",
                    (tokens, cost_usd, row[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO budget_tracking (agent_name, date, tokens_used, cost_usd, llm_calls) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (agent_name, today, tokens, cost_usd),
                )
            conn.commit()
        finally:
            conn.close()

        return cost_usd
    except Exception as e:
        logger.error("Failed to track cost for '%s': %s", agent_name, e)
        return 0.0


def check_budget(agent_name: str) -> dict[str, Any]:
    """Check whether an agent is within its budget limits.

    Sums daily and monthly spending from the database, compares against
    the agent's BudgetConfig, and returns a status dict.

    Args:
        agent_name: Name of the agent to check.

    Returns:
        Dict with keys: ok, daily_spent, monthly_spent, daily_limit,
        monthly_limit, remaining_today.
    """
    try:
        config = get_budget(agent_name)
        today = datetime.now().strftime("%Y-%m-%d")
        month_start = datetime.now().strftime("%Y-%m-01")

        conn = _get_conn()
        try:
            # Daily spend
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM budget_tracking "
                "WHERE agent_name = ? AND date = ?",
                (agent_name, today),
            ).fetchone()
            daily_spent = row[0] if row else 0.0

            # Monthly spend
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM budget_tracking "
                "WHERE agent_name = ? AND date >= ?",
                (agent_name, month_start),
            ).fetchone()
            monthly_spent = row[0] if row else 0.0
        finally:
            conn.close()

        remaining_today = max(0.0, config.daily_limit_usd - daily_spent)
        ok = (daily_spent < config.daily_limit_usd) and (monthly_spent < config.monthly_limit_usd)

        return {
            "ok": ok,
            "daily_spent": round(daily_spent, 6),
            "monthly_spent": round(monthly_spent, 6),
            "daily_limit": config.daily_limit_usd,
            "monthly_limit": config.monthly_limit_usd,
            "remaining_today": round(remaining_today, 6),
        }
    except Exception as e:
        logger.error("Failed to check budget for '%s': %s", agent_name, e)
        return {
            "ok": True,
            "daily_spent": 0.0,
            "monthly_spent": 0.0,
            "daily_limit": 1.0,
            "monthly_limit": 10.0,
            "remaining_today": 1.0,
        }


def get_spending_report(agent_name: str | None = None, days: int = 30) -> dict[str, Any]:
    """Generate a spending report for one or all agents.

    Queries the budget_tracking table for the specified time window and
    aggregates totals per agent and per day.

    Args:
        agent_name: Specific agent to report on, or None for all agents.
        days: Number of days to look back.

    Returns:
        Dict with total_cost, total_tokens, total_calls, and per-agent/day breakdown.
    """
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = _get_conn()
        try:
            if agent_name:
                rows = conn.execute(
                    "SELECT agent_name, date, tokens_used, cost_usd, llm_calls "
                    "FROM budget_tracking WHERE agent_name = ? AND date >= ? ORDER BY date DESC",
                    (agent_name, since),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT agent_name, date, tokens_used, cost_usd, llm_calls "
                    "FROM budget_tracking WHERE date >= ? ORDER BY date DESC",
                    (since,),
                ).fetchall()

            # Aggregate
            total_cost = 0.0
            total_tokens = 0
            total_calls = 0
            daily: list[dict[str, Any]] = []
            agents_summary: dict[str, dict[str, Any]] = {}

            for row in rows:
                a_name, date, tokens, cost, calls = row
                total_cost += cost
                total_tokens += tokens
                total_calls += calls
                daily.append({
                    "agent_name": a_name,
                    "date": date,
                    "tokens": tokens,
                    "cost_usd": round(cost, 6),
                    "llm_calls": calls,
                })
                if a_name not in agents_summary:
                    agents_summary[a_name] = {"total_cost": 0.0, "total_tokens": 0, "total_calls": 0}
                agents_summary[a_name]["total_cost"] += cost
                agents_summary[a_name]["total_tokens"] += tokens
                agents_summary[a_name]["total_calls"] += calls
        finally:
            conn.close()

        return {
            "total_cost": round(total_cost, 6),
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "days": days,
            "agents": {
                k: {
                    "total_cost": round(v["total_cost"], 6),
                    "total_tokens": v["total_tokens"],
                    "total_calls": v["total_calls"],
                }
                for k, v in agents_summary.items()
            },
            "daily": daily[:100],  # cap daily entries
        }
    except Exception as e:
        logger.error("Failed to generate spending report: %s", e)
        return {"total_cost": 0.0, "total_tokens": 0, "total_calls": 0, "days": days, "agents": {}, "daily": []}


def reset_daily_budgets() -> None:
    """Reset daily budget tracking by clearing today's records.

    Called at midnight by a scheduled hand. This is a no-op if there
    are no records for today (the next day's tracking starts fresh
    automatically via the date column).
    """
    try:
        logger.info("Daily budget reset triggered (new day starts fresh automatically)")
        # No actual deletion needed -- each day gets its own rows.
        # This function exists as a hook for any future cleanup logic.
    except Exception as e:
        logger.error("Failed to reset daily budgets: %s", e)
