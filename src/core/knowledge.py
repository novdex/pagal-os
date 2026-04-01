"""Knowledge graph — agents build connected knowledge over time.

Uses SQLite to store facts (nodes) and relationships (edges) so that
agents can remember, recall, and link information across runs.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Database path (kept for backward compatibility)
_DB_PATH = Path.home() / ".pagal-os" / "pagal.db"


def _get_connection() -> sqlite3.Connection:
    """Open (or create) the SQLite database and return a connection.

    Delegates to the central database module when available, falling
    back to a local connection if not. Uses the local path when
    ``_DB_PATH`` has been overridden (e.g. in tests).

    Returns:
        Active sqlite3.Connection with row_factory set to Row.
    """
    _default = Path.home() / ".pagal-os" / "pagal.db"
    if _DB_PATH == _default:
        try:
            from src.core.database import get_connection
            return get_connection()
        except Exception:
            pass
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    """Create the knowledge_nodes and knowledge_edges tables if they don't exist."""
    try:
        conn = _get_connection()
        conn.executescript("""
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
        """)
        conn.commit()
        conn.close()
        logger.info("Knowledge graph tables initialised.")
    except Exception as e:
        logger.error("Failed to initialise knowledge DB: %s", e)


def add_knowledge(
    agent_name: str,
    topic: str,
    content: str,
    source: str = "",
) -> int:
    """Add a fact to the knowledge graph.

    Args:
        agent_name: The agent that discovered this fact.
        topic: Short topic label (e.g. "python", "AI safety").
        content: The actual information / fact text.
        source: Where the fact came from (URL, filename, etc.).

    Returns:
        The new node ID, or -1 on failure.
    """
    try:
        init_db()
        conn = _get_connection()
        cursor = conn.execute(
            "INSERT INTO knowledge_nodes (agent_name, topic, content, source) "
            "VALUES (?, ?, ?, ?)",
            (agent_name, topic, content, source),
        )
        conn.commit()
        node_id = cursor.lastrowid or -1
        conn.close()
        logger.debug("Added knowledge node %d for agent '%s'", node_id, agent_name)
        return node_id
    except Exception as e:
        logger.error("Failed to add knowledge: %s", e)
        return -1


def link_knowledge(
    from_id: int,
    to_id: int,
    relation: str = "related_to",
) -> bool:
    """Connect two knowledge nodes with a labelled edge.

    Args:
        from_id: Source node ID.
        to_id: Target node ID.
        relation: Relationship label (e.g. "causes", "part_of").

    Returns:
        True if the edge was created, False on failure.
    """
    try:
        init_db()
        conn = _get_connection()
        conn.execute(
            "INSERT INTO knowledge_edges (from_id, to_id, relation) VALUES (?, ?, ?)",
            (from_id, to_id, relation),
        )
        conn.commit()
        conn.close()
        logger.debug("Linked knowledge %d -> %d (%s)", from_id, to_id, relation)
        return True
    except Exception as e:
        logger.error("Failed to link knowledge: %s", e)
        return False


def search_knowledge(
    query: str,
    agent_name: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search knowledge nodes by keyword in topic and content.

    Args:
        query: Search string (case-insensitive substring match).
        agent_name: Optional filter — only this agent's knowledge.
        limit: Max results to return.

    Returns:
        List of node dicts with id, agent_name, topic, content, source,
        created_at.
    """
    try:
        init_db()
        conn = _get_connection()
        pattern = f"%{query}%"

        if agent_name:
            rows = conn.execute(
                "SELECT * FROM knowledge_nodes "
                "WHERE agent_name = ? AND (topic LIKE ? OR content LIKE ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (agent_name, pattern, pattern, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_nodes "
                "WHERE topic LIKE ? OR content LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()

        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error("Knowledge search failed: %s", e)
        return []


def get_related(node_id: int, depth: int = 2) -> list[dict[str, Any]]:
    """Get facts connected to *node_id* up to *depth* hops away.

    Uses iterative breadth-first traversal through edges.

    Args:
        node_id: Starting node ID.
        depth: Maximum number of hops (default 2).

    Returns:
        List of related node dicts.
    """
    try:
        init_db()
        conn = _get_connection()

        visited: set[int] = set()
        frontier: set[int] = {node_id}

        for _ in range(depth):
            if not frontier:
                break

            placeholders = ",".join("?" * len(frontier))
            rows = conn.execute(
                f"SELECT to_id FROM knowledge_edges WHERE from_id IN ({placeholders}) "
                f"UNION "
                f"SELECT from_id FROM knowledge_edges WHERE to_id IN ({placeholders})",
                list(frontier) + list(frontier),
            ).fetchall()

            visited.update(frontier)
            frontier = {row["to_id"] if "to_id" in row.keys() else row[0] for row in rows} - visited

        # Collect all discovered node IDs (exclude the starting node)
        all_ids = (visited | frontier) - {node_id}

        if not all_ids:
            conn.close()
            return []

        placeholders = ",".join("?" * len(all_ids))
        nodes = conn.execute(
            f"SELECT * FROM knowledge_nodes WHERE id IN ({placeholders})",
            list(all_ids),
        ).fetchall()

        conn.close()
        return [dict(row) for row in nodes]
    except Exception as e:
        logger.error("Failed to get related knowledge: %s", e)
        return []


def auto_link(agent_name: str) -> int:
    """Automatically find and link related knowledge nodes by keyword overlap.

    Compares topics of all nodes belonging to *agent_name* and creates
    edges where topics share at least one word.

    Args:
        agent_name: The agent whose knowledge to auto-link.

    Returns:
        Number of new edges created.
    """
    try:
        init_db()
        conn = _get_connection()

        nodes = conn.execute(
            "SELECT id, topic FROM knowledge_nodes WHERE agent_name = ?",
            (agent_name,),
        ).fetchall()

        # Build a set of existing edges for dedup
        existing = set()
        edges = conn.execute(
            "SELECT from_id, to_id FROM knowledge_edges",
        ).fetchall()
        for edge in edges:
            existing.add((edge["from_id"], edge["to_id"]))
            existing.add((edge["to_id"], edge["from_id"]))

        created = 0
        node_list = [dict(n) for n in nodes]

        for i, a in enumerate(node_list):
            words_a = set(a["topic"].lower().split())
            for b in node_list[i + 1:]:
                words_b = set(b["topic"].lower().split())
                if words_a & words_b and (a["id"], b["id"]) not in existing:
                    conn.execute(
                        "INSERT INTO knowledge_edges (from_id, to_id, relation) "
                        "VALUES (?, ?, 'related_to')",
                        (a["id"], b["id"]),
                    )
                    existing.add((a["id"], b["id"]))
                    existing.add((b["id"], a["id"]))
                    created += 1

        conn.commit()
        conn.close()
        logger.info("Auto-linked %d edges for agent '%s'", created, agent_name)
        return created
    except Exception as e:
        logger.error("Auto-link failed: %s", e)
        return 0


def get_stats() -> dict[str, Any]:
    """Return high-level statistics about the knowledge graph.

    Returns:
        Dict with total_nodes, total_edges, topics (unique count), and
        top_topics list.
    """
    try:
        init_db()
        conn = _get_connection()

        total_nodes = conn.execute(
            "SELECT COUNT(*) as c FROM knowledge_nodes",
        ).fetchone()["c"]
        total_edges = conn.execute(
            "SELECT COUNT(*) as c FROM knowledge_edges",
        ).fetchone()["c"]
        topics = conn.execute(
            "SELECT DISTINCT topic FROM knowledge_nodes",
        ).fetchall()
        top_topics = conn.execute(
            "SELECT topic, COUNT(*) as c FROM knowledge_nodes "
            "GROUP BY topic ORDER BY c DESC LIMIT 10",
        ).fetchall()

        conn.close()
        return {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "unique_topics": len(topics),
            "top_topics": [{"topic": t["topic"], "count": t["c"]} for t in top_topics],
        }
    except Exception as e:
        logger.error("Failed to get knowledge stats: %s", e)
        return {"total_nodes": 0, "total_edges": 0, "unique_topics": 0, "top_topics": []}
