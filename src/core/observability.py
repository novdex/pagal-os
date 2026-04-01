"""PAGAL OS Agent Observability -- trace every LLM call, tool use, and decision.

Stores structured trace events in the ``agent_traces`` table inside the main
``pagal.db`` database so users can see exactly what an agent did during a run:
every LLM call, every tool invocation, every error, and every decision.
"""

import logging
import sqlite3
import uuid
from typing import Any

logger = logging.getLogger("pagal_os")


def _get_db() -> sqlite3.Connection:
    """Get a connection to the main PAGAL OS database for traces.

    Delegates to the central database module. Falls back to a direct
    connection if the module is unavailable.

    Returns:
        sqlite3 Connection with row_factory set to Row.
    """
    try:
        from src.core.database import get_connection
        return get_connection()
    except Exception:
        from pathlib import Path
        db_path = Path.home() / ".pagal-os" / "pagal.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn


def init_traces_db() -> None:
    """Create the agent_traces table if it doesn't already exist.

    Creates the table inside the main pagal.db. (Previously used a
    separate traces.db file, now consolidated.)
    """
    try:
        conn = _get_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT NOT NULL,
                duration_ms INTEGER DEFAULT 0,
                tokens INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_traces_run_id
            ON agent_traces(run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_traces_agent
            ON agent_traces(agent_name)
        """)
        conn.commit()
        conn.close()
        logger.debug("Traces tables initialised in main database")
    except Exception as e:
        logger.error("Failed to initialize traces DB: %s", e)


def start_trace(agent_name: str) -> str:
    """Start a new trace and return a unique run_id.

    Also logs the 'trace_start' event.

    Args:
        agent_name: Name of the agent being traced.

    Returns:
        A UUID-based run_id string.
    """
    try:
        init_traces_db()
        run_id = str(uuid.uuid4())[:12]
        log_trace(
            run_id=run_id,
            agent_name=agent_name,
            event_type="trace_start",
            content=f"Trace started for agent '{agent_name}'",
        )
        return run_id
    except Exception as e:
        logger.error("Failed to start trace: %s", e)
        return str(uuid.uuid4())[:12]


def log_trace(
    run_id: str,
    agent_name: str,
    event_type: str,
    content: str,
    duration_ms: int = 0,
    tokens: int = 0,
) -> None:
    """Log a single trace event.

    Args:
        run_id: The run ID from start_trace.
        agent_name: Name of the agent.
        event_type: One of 'llm_call', 'tool_call', 'tool_result',
                    'decision', 'error', 'trace_start', 'trace_end'.
        content: Human-readable description of the event.
        duration_ms: Duration of the event in milliseconds.
        tokens: Estimated token count (for LLM calls).
    """
    try:
        conn = _get_db()
        conn.execute(
            """INSERT INTO agent_traces
               (run_id, agent_name, event_type, content, duration_ms, tokens)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, agent_name, event_type, content[:5000], duration_ms, tokens),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("Failed to log trace event: %s", e)


def get_trace(run_id: str) -> list[dict[str, Any]]:
    """Get all events for a specific trace run.

    Args:
        run_id: The run ID.

    Returns:
        List of event dicts ordered by creation time.
    """
    try:
        conn = _get_db()
        cursor = conn.execute(
            """SELECT id, run_id, agent_name, event_type, content,
                      duration_ms, tokens, created_at
               FROM agent_traces
               WHERE run_id = ?
               ORDER BY id ASC""",
            (run_id,),
        )
        events = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return events
    except Exception as e:
        logger.error("Failed to get trace for run '%s': %s", run_id, e)
        return []


def get_recent_traces(
    agent_name: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get recent traces, optionally filtered by agent.

    Returns one entry per run_id with summary info.

    Args:
        agent_name: Optional agent name filter.
        limit: Max number of traces to return.

    Returns:
        List of trace summary dicts.
    """
    try:
        conn = _get_db()

        if agent_name:
            cursor = conn.execute(
                """SELECT run_id, agent_name,
                          MIN(created_at) AS started_at,
                          MAX(created_at) AS ended_at,
                          COUNT(*) AS event_count,
                          SUM(duration_ms) AS total_duration_ms,
                          SUM(tokens) AS total_tokens
                   FROM agent_traces
                   WHERE agent_name = ?
                   GROUP BY run_id
                   ORDER BY MAX(id) DESC
                   LIMIT ?""",
                (agent_name, limit),
            )
        else:
            cursor = conn.execute(
                """SELECT run_id, agent_name,
                          MIN(created_at) AS started_at,
                          MAX(created_at) AS ended_at,
                          COUNT(*) AS event_count,
                          SUM(duration_ms) AS total_duration_ms,
                          SUM(tokens) AS total_tokens
                   FROM agent_traces
                   GROUP BY run_id
                   ORDER BY MAX(id) DESC
                   LIMIT ?""",
                (limit,),
            )

        traces = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return traces
    except Exception as e:
        logger.error("Failed to get recent traces: %s", e)
        return []


def get_trace_summary(run_id: str) -> dict[str, Any]:
    """Get a summary of a trace run.

    Args:
        run_id: The run ID.

    Returns:
        Dict with total_time_ms, total_tokens, tool_calls_count,
        llm_calls_count, errors_count, and event_count.
    """
    try:
        events = get_trace(run_id)
        if not events:
            return {"ok": False, "error": "Trace not found"}

        total_time = sum(e.get("duration_ms", 0) for e in events)
        total_tokens = sum(e.get("tokens", 0) for e in events)
        tool_calls = sum(1 for e in events if e["event_type"] == "tool_call")
        llm_calls = sum(1 for e in events if e["event_type"] == "llm_call")
        errors = sum(1 for e in events if e["event_type"] == "error")

        return {
            "ok": True,
            "run_id": run_id,
            "agent_name": events[0].get("agent_name", ""),
            "event_count": len(events),
            "total_time_ms": total_time,
            "total_tokens": total_tokens,
            "tool_calls_count": tool_calls,
            "llm_calls_count": llm_calls,
            "errors_count": errors,
            "started_at": events[0].get("created_at", ""),
            "ended_at": events[-1].get("created_at", ""),
        }
    except Exception as e:
        logger.error("Failed to get trace summary for '%s': %s", run_id, e)
        return {"ok": False, "error": str(e)}
