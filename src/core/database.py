"""Database connection manager — single entry point for all SQLite access.

Centralises database connections so that every module uses the same path,
locking strategy, and table schema. Individual modules can still fall back
to their own connections if this module fails to import.
"""

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

_DB_PATH: Path = Path.home() / ".pagal-os" / "pagal.db"
_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """Get a connection to the main PAGAL OS database.

    Returns:
        An open sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def execute(sql: str, params: tuple = ()) -> list[Any]:
    """Execute a SQL statement and return all result rows.

    Acquires a thread lock so that concurrent writes are serialised.

    Args:
        sql: SQL statement (may contain ``?`` placeholders).
        params: Positional parameters for the statement.

    Returns:
        List of sqlite3.Row objects (empty for non-SELECT statements).
    """
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.execute(sql, params)
            results = cursor.fetchall()
            conn.commit()
            return results
        finally:
            conn.close()


def execute_many(sql: str, params_list: list[tuple]) -> int:
    """Execute a SQL statement for many parameter sets.

    Args:
        sql: SQL statement with ``?`` placeholders.
        params_list: List of parameter tuples.

    Returns:
        Number of rows affected.
    """
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.executemany(sql, params_list)
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


def init_all_tables() -> None:
    """Create every table used by PAGAL OS modules, if they don't exist.

    Safe to call multiple times — all statements use IF NOT EXISTS.
    This is the canonical schema definition for the entire application.
    """
    conn = get_connection()
    try:
        conn.executescript("""
            -- Knowledge graph
            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS knowledge_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id INTEGER REFERENCES knowledge_nodes(id),
                to_id INTEGER REFERENCES knowledge_nodes(id),
                relation TEXT DEFAULT 'related_to',
                weight REAL DEFAULT 1.0
            );

            CREATE INDEX IF NOT EXISTS idx_kn_agent
                ON knowledge_nodes(agent_name);
            CREATE INDEX IF NOT EXISTS idx_kn_topic
                ON knowledge_nodes(topic);

            -- Analytics
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
            );

            -- Cross-session memory
            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS memory_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                summary TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_memory_agent
                ON agent_memory(agent_name, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_session
                ON agent_memory(agent_name, session_id);
            CREATE INDEX IF NOT EXISTS idx_summary_agent
                ON memory_summaries(agent_name, created_at DESC);

            -- Budget tracking
            CREATE TABLE IF NOT EXISTS budget_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                date TEXT NOT NULL,
                tokens_used INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                llm_calls INTEGER DEFAULT 0
            );

            -- Autonomous goals
            CREATE TABLE IF NOT EXISTS agent_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                progress_pct INTEGER DEFAULT 0,
                sub_tasks TEXT DEFAULT '[]',
                completed_tasks TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_worked_at TIMESTAMP,
                notes TEXT DEFAULT ''
            );

            -- Agent traces (previously in separate traces.db)
            CREATE TABLE IF NOT EXISTS agent_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT NOT NULL,
                duration_ms INTEGER DEFAULT 0,
                tokens INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_traces_run_id
                ON agent_traces(run_id);
            CREATE INDEX IF NOT EXISTS idx_traces_agent
                ON agent_traces(agent_name);

            -- Credits (previously in separate credits.db)
            CREATE TABLE IF NOT EXISTS credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'local',
                balance REAL DEFAULT 100.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS credit_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                agent_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        logger.info("All database tables initialised in %s", _DB_PATH)
    except Exception as e:
        logger.error("Failed to initialise database tables: %s", e)
    finally:
        conn.close()


def init_traces_tables() -> None:
    """Create the traces tables in the main pagal.db.

    Backward-compatible wrapper -- traces are now part of init_all_tables().
    Safe to call independently; delegates to init_all_tables().
    """
    init_all_tables()


def init_credits_tables() -> None:
    """Create the credits tables in the main pagal.db.

    Backward-compatible wrapper -- credits are now part of init_all_tables().
    Safe to call independently; delegates to init_all_tables().
    """
    init_all_tables()
