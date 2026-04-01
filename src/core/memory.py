"""PAGAL OS Cross-Session Memory — agents remember past conversations across sessions.

Uses SQLite (stored in ~/.pagal-os/pagal.db) to persist message history and
generate summaries so agents retain context even when the user returns later.
"""

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Database path inside the PAGAL OS storage directory
_DB_PATH: Path = Path.home() / ".pagal-os" / "pagal.db"


def _get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode for concurrent reads.

    Returns:
        An open sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_memory_db() -> None:
    """Create the agent_memory and memory_summaries tables if they don't exist.

    Safe to call multiple times — uses IF NOT EXISTS.
    """
    try:
        conn = _get_connection()
        conn.executescript("""
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
        """)
        conn.commit()
        conn.close()
        logger.debug("Memory DB initialised at %s", _DB_PATH)
    except Exception as e:
        logger.error("Failed to initialise memory DB: %s", e)


def generate_session_id() -> str:
    """Generate a unique session ID.

    Returns:
        A UUID4 hex string for the current session.
    """
    return uuid.uuid4().hex[:16]


def save_message(
    agent_name: str,
    session_id: str,
    role: str,
    content: str,
    importance: float = 0.5,
) -> None:
    """Save a single message to persistent memory.

    Args:
        agent_name: The agent this message belongs to.
        session_id: Current session identifier.
        role: Either 'user' or 'assistant'.
        content: The message text.
        importance: Score from 0.0 to 1.0 (default 0.5).
    """
    try:
        conn = _get_connection()
        conn.execute(
            """INSERT INTO agent_memory (agent_name, session_id, role, content, importance)
               VALUES (?, ?, ?, ?, ?)""",
            (agent_name, session_id, role, content[:10000], max(0.0, min(1.0, importance))),
        )
        conn.commit()
        conn.close()
        logger.debug("Saved %s message for agent '%s'", role, agent_name)
    except Exception as e:
        logger.error("Failed to save message for agent '%s': %s", agent_name, e)


def get_recent_messages(agent_name: str, limit: int = 20) -> list[dict[str, Any]]:
    """Get the most recent messages for an agent across ALL sessions.

    Args:
        agent_name: The agent to retrieve messages for.
        limit: Maximum number of messages to return (newest first).

    Returns:
        List of message dicts with keys: id, session_id, role, content, importance, created_at.
    """
    try:
        conn = _get_connection()
        rows = conn.execute(
            """SELECT id, session_id, role, content, importance, created_at
               FROM agent_memory
               WHERE agent_name = ?
               ORDER BY created_at DESC, id DESC
               LIMIT ?""",
            (agent_name, limit),
        ).fetchall()
        conn.close()
        # Return in chronological order (oldest first)
        return [dict(r) for r in reversed(rows)]
    except Exception as e:
        logger.error("Failed to get recent messages for '%s': %s", agent_name, e)
        return []


def get_session_messages(agent_name: str, session_id: str) -> list[dict[str, Any]]:
    """Get all messages from a specific session.

    Args:
        agent_name: The agent to retrieve messages for.
        session_id: The session to filter by.

    Returns:
        List of message dicts in chronological order.
    """
    try:
        conn = _get_connection()
        rows = conn.execute(
            """SELECT id, session_id, role, content, importance, created_at
               FROM agent_memory
               WHERE agent_name = ? AND session_id = ?
               ORDER BY created_at ASC""",
            (agent_name, session_id),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Failed to get session messages for '%s': %s", agent_name, e)
        return []


def summarize_old_messages(agent_name: str, keep_recent: int = 20) -> int:
    """Summarize old messages into memory_summaries and delete originals.

    Keeps the most recent `keep_recent` messages intact. Older messages are
    concatenated into a summary and stored in memory_summaries, then deleted.

    Args:
        agent_name: The agent whose messages to summarize.
        keep_recent: How many recent messages to keep as-is.

    Returns:
        Number of messages summarized (0 if none were old enough).
    """
    try:
        conn = _get_connection()

        # Count total messages
        total = conn.execute(
            "SELECT COUNT(*) FROM agent_memory WHERE agent_name = ?",
            (agent_name,),
        ).fetchone()[0]

        if total <= keep_recent:
            conn.close()
            return 0

        # Get old messages (everything except the most recent `keep_recent`)
        old_rows = conn.execute(
            """SELECT id, role, content, created_at
               FROM agent_memory
               WHERE agent_name = ?
               ORDER BY created_at ASC
               LIMIT ?""",
            (agent_name, total - keep_recent),
        ).fetchall()

        if not old_rows:
            conn.close()
            return 0

        # Build summary text from old messages
        summary_parts: list[str] = []
        for row in old_rows:
            role_label = "User" if row["role"] == "user" else "Agent"
            # Truncate very long messages in summary
            content = row["content"][:200]
            summary_parts.append(f"[{row['created_at']}] {role_label}: {content}")

        summary_text = (
            f"Summary of {len(old_rows)} earlier messages "
            f"({old_rows[0]['created_at']} to {old_rows[-1]['created_at']}):\n"
            + "\n".join(summary_parts)
        )

        # Truncate summary if it gets too long
        if len(summary_text) > 5000:
            summary_text = summary_text[:5000] + "\n... (truncated)"

        # Save summary
        conn.execute(
            """INSERT INTO memory_summaries (agent_name, summary, message_count)
               VALUES (?, ?, ?)""",
            (agent_name, summary_text, len(old_rows)),
        )

        # Delete old messages
        old_ids = [row["id"] for row in old_rows]
        placeholders = ",".join("?" * len(old_ids))
        conn.execute(
            f"DELETE FROM agent_memory WHERE id IN ({placeholders})",
            old_ids,
        )

        conn.commit()
        conn.close()

        logger.info(
            "Summarized %d old messages for agent '%s'",
            len(old_rows), agent_name,
        )
        return len(old_rows)

    except Exception as e:
        logger.error("Failed to summarize messages for '%s': %s", agent_name, e)
        return 0


def get_memory_context(agent_name: str) -> str:
    """Build a context string from summaries + recent messages for injection into system prompt.

    This is the main entry point used by the runtime: it returns a single
    string with all the agent's long-term memory that can be prepended to
    the system message.

    Args:
        agent_name: The agent to build context for.

    Returns:
        A formatted string with past conversation summaries and recent messages.
        Returns empty string if there's no memory.
    """
    try:
        conn = _get_connection()

        # Get summaries (most recent 5)
        summaries = conn.execute(
            """SELECT summary, message_count, created_at
               FROM memory_summaries
               WHERE agent_name = ?
               ORDER BY created_at DESC
               LIMIT 5""",
            (agent_name,),
        ).fetchall()

        # Get recent messages (last 10 for context, not 20 to save tokens)
        recent = conn.execute(
            """SELECT role, content, created_at
               FROM agent_memory
               WHERE agent_name = ?
               ORDER BY created_at DESC
               LIMIT 10""",
            (agent_name,),
        ).fetchall()

        conn.close()

        if not summaries and not recent:
            return ""

        parts: list[str] = ["=== MEMORY FROM PAST CONVERSATIONS ==="]

        if summaries:
            parts.append("\n--- Past Conversation Summaries ---")
            for s in reversed(list(summaries)):
                parts.append(s["summary"])

        if recent:
            parts.append("\n--- Recent Messages ---")
            for msg in reversed(list(recent)):
                role_label = "User" if msg["role"] == "user" else "You"
                content = msg["content"][:300]
                parts.append(f"{role_label}: {content}")

        parts.append("=== END MEMORY ===\n")
        return "\n".join(parts)

    except Exception as e:
        logger.error("Failed to get memory context for '%s': %s", agent_name, e)
        return ""


def search_memory(agent_name: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Keyword search across all memory (messages + summaries) for an agent.

    Args:
        agent_name: The agent to search memory for.
        query: Search keywords (uses SQLite LIKE with wildcards).
        limit: Maximum results to return.

    Returns:
        List of matching dicts with keys: source ('message' or 'summary'), content, created_at.
    """
    try:
        conn = _get_connection()
        like_pattern = f"%{query}%"

        # Search messages
        msg_rows = conn.execute(
            """SELECT 'message' AS source, role, content, created_at
               FROM agent_memory
               WHERE agent_name = ? AND content LIKE ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (agent_name, like_pattern, limit),
        ).fetchall()

        # Search summaries
        sum_rows = conn.execute(
            """SELECT 'summary' AS source, 'summary' AS role, summary AS content, created_at
               FROM memory_summaries
               WHERE agent_name = ? AND summary LIKE ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (agent_name, like_pattern, limit),
        ).fetchall()

        conn.close()

        results = [dict(r) for r in msg_rows] + [dict(r) for r in sum_rows]
        # Sort combined by created_at descending
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    except Exception as e:
        logger.error("Failed to search memory for '%s': %s", agent_name, e)
        return []


def get_memory_stats(agent_name: str | None = None) -> dict[str, Any]:
    """Get memory statistics for an agent or all agents.

    Args:
        agent_name: Optional agent name to filter by. If None, returns global stats.

    Returns:
        Dict with total_messages, total_summaries, and per-agent breakdowns.
    """
    try:
        conn = _get_connection()

        if agent_name:
            msg_count = conn.execute(
                "SELECT COUNT(*) FROM agent_memory WHERE agent_name = ?",
                (agent_name,),
            ).fetchone()[0]
            sum_count = conn.execute(
                "SELECT COUNT(*) FROM memory_summaries WHERE agent_name = ?",
                (agent_name,),
            ).fetchone()[0]
            conn.close()
            return {
                "agent": agent_name,
                "total_messages": msg_count,
                "total_summaries": sum_count,
            }

        msg_count = conn.execute("SELECT COUNT(*) FROM agent_memory").fetchone()[0]
        sum_count = conn.execute("SELECT COUNT(*) FROM memory_summaries").fetchone()[0]

        agents = conn.execute(
            """SELECT agent_name, COUNT(*) AS cnt
               FROM agent_memory
               GROUP BY agent_name
               ORDER BY cnt DESC""",
        ).fetchall()

        conn.close()
        return {
            "total_messages": msg_count,
            "total_summaries": sum_count,
            "agents": [{"agent": r["agent_name"], "messages": r["cnt"]} for r in agents],
        }

    except Exception as e:
        logger.error("Failed to get memory stats: %s", e)
        return {"total_messages": 0, "total_summaries": 0, "agents": []}


# Initialise tables on import
init_memory_db()
