"""Smart Memory — Mem0-style fact extraction and temporal knowledge graph.

Goes beyond message history: extracts structured FACTS from conversations
and stores them with temporal validity. Facts are auto-injected into agent
context so they "know" the user without being told repeatedly.

Example facts:
  - "User is allergic to peanuts" (permanent)
  - "User is on vacation until April 15" (expires 2026-04-15)
  - "User's boss is named Sarah" (permanent)
  - "User prefers dark mode" (preference)
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

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


def init_smart_memory_db() -> None:
    """Create the smart_facts table."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS smart_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL DEFAULT '_global',
                category TEXT NOT NULL DEFAULT 'general',
                fact TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                source TEXT DEFAULT '',
                expires_at TIMESTAMP DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_sf_agent ON smart_facts(agent_name);
            CREATE INDEX IF NOT EXISTS idx_sf_category ON smart_facts(category);
        """)
        conn.commit()
    finally:
        conn.close()


def add_fact(
    fact: str,
    agent_name: str = "_global",
    category: str = "general",
    confidence: float = 1.0,
    source: str = "",
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Store a fact about the user or context.

    Args:
        fact: The fact text (e.g. "User is allergic to peanuts").
        agent_name: Agent this fact belongs to (_global = all agents).
        category: One of: preference, personal, work, health, general, temporary.
        confidence: How confident we are (0.0-1.0).
        source: Where this fact came from.
        expires_at: ISO date when this fact expires (None = permanent).

    Returns:
        Dict with 'ok' and fact ID.
    """
    try:
        init_smart_memory_db()
        conn = _get_conn()
        try:
            # Check for duplicate/update existing
            existing = conn.execute(
                "SELECT id FROM smart_facts WHERE agent_name = ? AND fact = ?",
                (agent_name, fact),
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE smart_facts SET confidence = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (confidence, existing["id"]),
                )
                conn.commit()
                return {"ok": True, "id": existing["id"], "message": "Fact updated"}

            cursor = conn.execute(
                """INSERT INTO smart_facts (agent_name, category, fact, confidence, source, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (agent_name, category, fact, confidence, source, expires_at),
            )
            conn.commit()
            return {"ok": True, "id": cursor.lastrowid}
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_facts(
    agent_name: str = "_global",
    category: str | None = None,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve all active facts for an agent.

    Args:
        agent_name: Agent to get facts for (also includes _global).
        category: Optional category filter.
        include_expired: Whether to include expired facts.

    Returns:
        List of fact dicts.
    """
    try:
        init_smart_memory_db()
        conn = _get_conn()
        try:
            query = "SELECT * FROM smart_facts WHERE agent_name IN (?, '_global')"
            params: list[Any] = [agent_name]

            if category:
                query += " AND category = ?"
                params.append(category)

            if not include_expired:
                query += " AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)"

            query += " ORDER BY confidence DESC, updated_at DESC"

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        return []


def forget_fact(fact_id: int) -> dict[str, Any]:
    """Delete a specific fact."""
    try:
        conn = _get_conn()
        try:
            conn.execute("DELETE FROM smart_facts WHERE id = ?", (fact_id,))
            conn.commit()
            return {"ok": True}
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def extract_facts_from_text(text: str, agent_name: str = "_global") -> list[dict[str, Any]]:
    """Extract structured facts from conversation text using pattern matching.

    Looks for statements like:
      - "I am ...", "I have ...", "I like ...", "I prefer ..."
      - "My name is ...", "My job is ...", "I work at ..."
      - "I'm allergic to ...", "I don't eat ..."
      - "Remember that ...", "Note that ..."

    Args:
        text: Conversation text to extract facts from.
        agent_name: Agent to associate facts with.

    Returns:
        List of extracted facts.
    """
    import re

    patterns = [
        (r"(?:I am|I'm)\s+(.{5,80}?)(?:\.|,|!|\?|$)", "personal"),
        (r"(?:my name is|I'm called)\s+(\w+(?:\s+\w+)?)", "personal"),
        (r"(?:I work at|I work for|my company is)\s+(.{3,50}?)(?:\.|,|$)", "work"),
        (r"(?:I like|I love|I prefer|I enjoy)\s+(.{3,60}?)(?:\.|,|!|$)", "preference"),
        (r"(?:I don't like|I hate|I dislike)\s+(.{3,60}?)(?:\.|,|!|$)", "preference"),
        (r"(?:I'm allergic to|I can't eat|I avoid)\s+(.{3,40}?)(?:\.|,|$)", "health"),
        (r"(?:remember that|note that|keep in mind)\s+(.{5,100}?)(?:\.|!|$)", "general"),
        (r"(?:my (?:email|phone|address) is)\s+(.{5,60}?)(?:\.|,|$)", "personal"),
    ]

    extracted: list[dict[str, Any]] = []

    for pattern, category in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            fact_text = match.strip().rstrip(".,!?")
            if len(fact_text) > 3:
                result = add_fact(
                    fact=fact_text,
                    agent_name=agent_name,
                    category=category,
                    source="conversation_extraction",
                    confidence=0.8,
                )
                if result.get("ok"):
                    extracted.append({"fact": fact_text, "category": category})

    return extracted


def build_fact_context(agent_name: str = "_global") -> str:
    """Build a context string from stored facts for injection into agent prompts.

    Args:
        agent_name: Agent to build context for.

    Returns:
        Formatted string of facts, or empty string if none.
    """
    facts = get_facts(agent_name)
    if not facts:
        return ""

    lines = ["[User Facts — remembered from previous conversations]"]
    for f in facts[:20]:  # Limit to 20 most relevant
        prefix = f"[{f['category']}]" if f.get("category") != "general" else ""
        lines.append(f"- {prefix} {f['fact']}")

    return "\n".join(lines)
