"""Credits System -- earn credits when others use your agents.

Virtual credits economy for the PAGAL OS marketplace.
Uses the main pagal.db database for persistent storage.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Starting balance for new users
_STARTING_BALANCE = 100.0

# Credit costs per model tier
CREDIT_COSTS: dict[str, float] = {
    "free": 1.0,
    "cheap": 2.0,
    "mid": 3.0,
    "premium": 5.0,
}


def _get_conn() -> sqlite3.Connection:
    """Get a SQLite connection to the main PAGAL OS database.

    Delegates to the central database module. Falls back to a direct
    connection to pagal.db if the module is unavailable.

    Returns:
        sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    try:
        from src.core.database import get_connection
        return get_connection()
    except Exception:
        db_path = Path.home() / ".pagal-os" / "pagal.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn


def init_credits_db() -> None:
    """Create the credits tables and give 100 free credits to the local user.

    Creates tables inside the main pagal.db. (Previously used a separate
    credits.db file, now consolidated.) Safe to call multiple times --
    uses IF NOT EXISTS.
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'local',
                balance REAL DEFAULT 100.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS credit_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                agent_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Ensure the local user has a record
        cursor.execute("SELECT id FROM credits WHERE user_id = 'local'")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO credits (user_id, balance) VALUES ('local', ?)",
                (_STARTING_BALANCE,),
            )
            cursor.execute(
                "INSERT INTO credit_transactions (user_id, amount, description, agent_name) "
                "VALUES ('local', ?, 'Welcome bonus -- 100 free credits', '')",
                (_STARTING_BALANCE,),
            )

        conn.commit()
        conn.close()
        logger.info("Credits tables initialised in main database")

    except Exception as e:
        logger.error("Failed to initialise credits database: %s", e)


def get_balance(user_id: str = "local") -> float:
    """Get the current credit balance for a user.

    Args:
        user_id: User identifier (default 'local').

    Returns:
        Current balance as a float. Returns 0.0 if user not found.
    """
    try:
        init_credits_db()
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT balance FROM credits WHERE user_id = ?", (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return float(row["balance"]) if row else 0.0
    except Exception as e:
        logger.error("Failed to get balance for '%s': %s", user_id, e)
        return 0.0


def spend_credits(
    user_id: str,
    amount: float,
    agent_name: str,
    description: str,
) -> bool:
    """Deduct credits from a user's balance.

    Args:
        user_id: User identifier.
        amount: Amount to deduct (must be positive).
        agent_name: The agent that caused the spend.
        description: Reason for the deduction.

    Returns:
        True if credits were deducted, False if insufficient balance.
    """
    try:
        if amount <= 0:
            logger.warning("Invalid spend amount: %s", amount)
            return False

        init_credits_db()
        conn = _get_conn()
        cursor = conn.cursor()

        # Check balance
        cursor.execute(
            "SELECT balance FROM credits WHERE user_id = ?", (user_id,),
        )
        row = cursor.fetchone()

        if row is None or float(row["balance"]) < amount:
            conn.close()
            logger.warning(
                "Insufficient credits for user '%s': need %.1f, have %.1f",
                user_id, amount, float(row["balance"]) if row else 0.0,
            )
            return False

        # Deduct
        cursor.execute(
            "UPDATE credits SET balance = balance - ? WHERE user_id = ?",
            (amount, user_id),
        )
        cursor.execute(
            "INSERT INTO credit_transactions (user_id, amount, description, agent_name) "
            "VALUES (?, ?, ?, ?)",
            (user_id, -amount, description, agent_name),
        )
        conn.commit()
        conn.close()

        logger.info(
            "User '%s' spent %.1f credits on agent '%s'",
            user_id, amount, agent_name,
        )
        return True

    except Exception as e:
        logger.error("Failed to spend credits: %s", e)
        return False


def earn_credits(
    user_id: str,
    amount: float,
    agent_name: str,
    description: str,
) -> bool:
    """Add credits to a user's balance.

    Args:
        user_id: User identifier.
        amount: Amount to add (must be positive).
        agent_name: The agent that earned credits.
        description: Reason for the credit.

    Returns:
        True if credits were added successfully.
    """
    try:
        if amount <= 0:
            logger.warning("Invalid earn amount: %s", amount)
            return False

        init_credits_db()
        conn = _get_conn()
        cursor = conn.cursor()

        # Ensure user exists
        cursor.execute(
            "SELECT id FROM credits WHERE user_id = ?", (user_id,),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO credits (user_id, balance) VALUES (?, ?)",
                (user_id, 0.0),
            )

        # Add credits
        cursor.execute(
            "UPDATE credits SET balance = balance + ? WHERE user_id = ?",
            (amount, user_id),
        )
        cursor.execute(
            "INSERT INTO credit_transactions (user_id, amount, description, agent_name) "
            "VALUES (?, ?, ?, ?)",
            (user_id, amount, description, agent_name),
        )
        conn.commit()
        conn.close()

        logger.info(
            "User '%s' earned %.1f credits from agent '%s'",
            user_id, amount, agent_name,
        )
        return True

    except Exception as e:
        logger.error("Failed to earn credits: %s", e)
        return False


def get_transactions(user_id: str = "local", limit: int = 50) -> list[dict[str, Any]]:
    """Get recent transaction history for a user.

    Args:
        user_id: User identifier.
        limit: Maximum number of transactions to return.

    Returns:
        List of transaction dicts with amount, description, agent_name,
        and created_at fields.
    """
    try:
        init_credits_db()
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, user_id, amount, description, agent_name, created_at "
            "FROM credit_transactions WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "amount": row["amount"],
                "description": row["description"],
                "agent_name": row["agent_name"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    except Exception as e:
        logger.error("Failed to get transactions: %s", e)
        return []


def get_credit_cost(model: str) -> float:
    """Determine credit cost based on model tier.

    Free models cost 1 credit, paid models cost up to 5.

    Args:
        model: The model name/identifier.

    Returns:
        Number of credits this model costs per run.
    """
    model_lower = model.lower()

    if ":free" in model_lower or "free" in model_lower:
        return CREDIT_COSTS["free"]
    elif "gpt-4" in model_lower or "claude-3-opus" in model_lower:
        return CREDIT_COSTS["premium"]
    elif "gpt-3.5" in model_lower or "claude-3-haiku" in model_lower:
        return CREDIT_COSTS["cheap"]
    else:
        return CREDIT_COSTS["mid"]
