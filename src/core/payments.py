"""Stripe Payments — agents that earn money.

Enables agent creators to charge for their agents. Supports:
  - Pay-per-use: charge per agent run
  - Subscription: monthly access fee
  - Free tier: limited runs per month

Requires: STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET env vars.
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

_STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "")
_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

_DB_PATH = Path.home() / ".pagal-os" / "pagal.db"


def _get_conn() -> sqlite3.Connection:
    try:
        from src.core.database import get_connection
        return get_connection()
    except Exception:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn


def init_payments_db() -> None:
    """Create payment tables."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_pricing (
                agent_name TEXT PRIMARY KEY,
                pricing_model TEXT DEFAULT 'free',
                price_per_use REAL DEFAULT 0.0,
                monthly_price REAL DEFAULT 0.0,
                free_runs_per_month INTEGER DEFAULT 10,
                stripe_price_id TEXT DEFAULT '',
                creator_stripe_account TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS payment_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'local',
                agent_name TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'usd',
                stripe_payment_id TEXT DEFAULT '',
                status TEXT DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS agent_usage_quotas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'local',
                agent_name TEXT NOT NULL,
                runs_this_month INTEGER DEFAULT 0,
                month TEXT NOT NULL,
                UNIQUE(user_id, agent_name, month)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def set_agent_pricing(
    agent_name: str,
    pricing_model: str = "free",
    price_per_use: float = 0.0,
    monthly_price: float = 0.0,
    free_runs_per_month: int = 10,
) -> dict[str, Any]:
    """Set pricing for an agent.

    Args:
        agent_name: Agent to price.
        pricing_model: 'free', 'pay_per_use', or 'subscription'.
        price_per_use: Cost per run in USD (for pay_per_use).
        monthly_price: Monthly subscription price in USD.
        free_runs_per_month: Free runs before charging.

    Returns:
        Dict with 'ok' status.
    """
    try:
        init_payments_db()
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO agent_pricing
                   (agent_name, pricing_model, price_per_use, monthly_price, free_runs_per_month)
                   VALUES (?, ?, ?, ?, ?)""",
                (agent_name, pricing_model, price_per_use, monthly_price, free_runs_per_month),
            )
            conn.commit()
            return {"ok": True, "message": f"Pricing set for {agent_name}: {pricing_model}"}
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_usage_quota(agent_name: str, user_id: str = "local") -> dict[str, Any]:
    """Check if a user can run an agent (within free tier or paid).

    Returns:
        Dict with 'allowed' (bool), 'reason', 'runs_used', 'runs_limit'.
    """
    try:
        init_payments_db()
        conn = _get_conn()
        try:
            # Get pricing
            pricing = conn.execute(
                "SELECT * FROM agent_pricing WHERE agent_name = ?", (agent_name,)
            ).fetchone()

            if not pricing or pricing["pricing_model"] == "free":
                return {"allowed": True, "reason": "free agent", "runs_used": 0, "runs_limit": -1}

            # Check this month's usage
            month = time.strftime("%Y-%m")
            usage = conn.execute(
                "SELECT runs_this_month FROM agent_usage_quotas WHERE user_id = ? AND agent_name = ? AND month = ?",
                (user_id, agent_name, month),
            ).fetchone()

            runs_used = usage["runs_this_month"] if usage else 0
            free_limit = pricing["free_runs_per_month"]

            if runs_used < free_limit:
                return {
                    "allowed": True, "reason": "within free tier",
                    "runs_used": runs_used, "runs_limit": free_limit,
                }

            # Over free tier — need payment
            if pricing["pricing_model"] == "pay_per_use":
                return {
                    "allowed": True, "reason": "pay_per_use",
                    "runs_used": runs_used, "runs_limit": free_limit,
                    "charge_amount": pricing["price_per_use"],
                }

            return {
                "allowed": False,
                "reason": f"Free tier exceeded ({runs_used}/{free_limit}). Upgrade to continue.",
                "runs_used": runs_used, "runs_limit": free_limit,
            }
        finally:
            conn.close()
    except Exception as e:
        return {"allowed": True, "reason": f"quota check failed: {e}"}


def record_usage(agent_name: str, user_id: str = "local") -> None:
    """Record an agent run for quota tracking."""
    try:
        init_payments_db()
        month = time.strftime("%Y-%m")
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO agent_usage_quotas (user_id, agent_name, runs_this_month, month)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(user_id, agent_name, month)
                   DO UPDATE SET runs_this_month = runs_this_month + 1""",
                (user_id, agent_name, month),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def get_agent_pricing(agent_name: str) -> dict[str, Any]:
    """Get pricing info for an agent."""
    try:
        init_payments_db()
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM agent_pricing WHERE agent_name = ?", (agent_name,)
            ).fetchone()
            return dict(row) if row else {"pricing_model": "free", "price_per_use": 0, "monthly_price": 0}
        finally:
            conn.close()
    except Exception:
        return {"pricing_model": "free"}


def get_revenue_report(creator_id: str = "local") -> dict[str, Any]:
    """Get revenue summary for an agent creator."""
    try:
        init_payments_db()
        conn = _get_conn()
        try:
            rows = conn.execute(
                """SELECT agent_name, SUM(amount) as total, COUNT(*) as transactions
                   FROM payment_transactions WHERE status = 'completed'
                   GROUP BY agent_name ORDER BY total DESC""",
            ).fetchall()
            return {
                "ok": True,
                "agents": [dict(r) for r in rows],
                "total_revenue": sum(r["total"] for r in rows),
            }
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
