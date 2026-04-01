"""PAGAL OS Agent Logs Export — export traces, analytics, knowledge, and memory.

Export agent data as CSV or JSON for external analysis tools. All exports
are saved to ``~/.pagal-os/exports/`` with timestamped filenames.
"""

import csv
import io
import json
import logging
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Export output directory
_PAGAL_DIR = Path.home() / ".pagal-os"
EXPORTS_DIR = _PAGAL_DIR / "exports"


def _ensure_exports_dir() -> None:
    """Create the exports directory if it doesn't exist."""
    try:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error("Failed to create exports directory: %s", e)


def _timestamp_str() -> str:
    """Return a filesystem-safe timestamp string for filenames.

    Returns:
        Timestamp like '20260330_143021'.
    """
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _write_json(data: Any, file_path: Path) -> str:
    """Write data as indented JSON to a file.

    Args:
        data: Serializable data.
        file_path: Output path.

    Returns:
        Absolute path string of the written file.
    """
    try:
        file_path.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8",
        )
        logger.info("Exported JSON to %s", file_path)
        return str(file_path)
    except Exception as e:
        logger.error("Failed to write JSON export: %s", e)
        raise


def _write_csv(rows: list[dict], file_path: Path) -> str:
    """Write a list of dicts as CSV to a file.

    Args:
        rows: List of row dicts. Keys become headers.
        file_path: Output path.

    Returns:
        Absolute path string of the written file.
    """
    try:
        if not rows:
            file_path.write_text("", encoding="utf-8")
            return str(file_path)

        headers = list(rows[0].keys())
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

        logger.info("Exported CSV to %s", file_path)
        return str(file_path)
    except Exception as e:
        logger.error("Failed to write CSV export: %s", e)
        raise


def _get_db(db_name: str = "pagal.db") -> sqlite3.Connection:
    """Open a SQLite database from the PAGAL OS storage directory.

    All tables are now consolidated in pagal.db. The ``db_name`` parameter
    is kept for backward compatibility but defaults to 'pagal.db'.

    Args:
        db_name: Database filename (defaults to 'pagal.db').

    Returns:
        sqlite3 Connection with row_factory set to Row.
    """
    # Redirect legacy separate DB names to the main database
    if db_name in ("traces.db", "credits.db"):
        db_name = "pagal.db"

    db_path = _PAGAL_DIR / db_name
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def export_traces(
    agent_name: str | None = None,
    format: str = "json",
    days: int = 30,
) -> str:
    """Export agent traces to a file.

    Args:
        agent_name: Filter to a specific agent (None = all agents).
        format: Output format — 'json' or 'csv'.
        days: How many days of traces to export.

    Returns:
        Absolute file path of the exported file.
    """
    _ensure_exports_dir()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        conn = _get_db("traces.db")
        if agent_name:
            rows = conn.execute(
                "SELECT * FROM agent_traces WHERE agent_name = ? AND created_at >= ? ORDER BY created_at DESC",
                (agent_name, cutoff),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_traces WHERE created_at >= ? ORDER BY created_at DESC",
                (cutoff,),
            ).fetchall()
        conn.close()
    except Exception as e:
        logger.warning("Could not read traces DB: %s", e)
        rows = []

    data = [dict(r) for r in rows]
    suffix = agent_name or "all"
    ext = "csv" if format == "csv" else "json"
    file_path = EXPORTS_DIR / f"traces_{suffix}_{_timestamp_str()}.{ext}"

    if format == "csv":
        return _write_csv(data, file_path)
    return _write_json(data, file_path)


def export_analytics(
    agent_name: str | None = None,
    format: str = "json",
    days: int = 30,
) -> str:
    """Export analytics/run data to a file.

    Args:
        agent_name: Filter to a specific agent (None = all agents).
        format: Output format — 'json' or 'csv'.
        days: How many days of data to export.

    Returns:
        Absolute file path of the exported file.
    """
    _ensure_exports_dir()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        conn = _get_db("pagal.db")
        if agent_name:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE agent_name = ? AND created_at >= ? ORDER BY created_at DESC",
                (agent_name, cutoff),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE created_at >= ? ORDER BY created_at DESC",
                (cutoff,),
            ).fetchall()
        conn.close()
    except Exception as e:
        logger.warning("Could not read analytics from pagal.db: %s", e)
        rows = []

    data = [dict(r) for r in rows]
    suffix = agent_name or "all"
    ext = "csv" if format == "csv" else "json"
    file_path = EXPORTS_DIR / f"analytics_{suffix}_{_timestamp_str()}.{ext}"

    if format == "csv":
        return _write_csv(data, file_path)
    return _write_json(data, file_path)


def export_knowledge(
    agent_name: str | None = None,
    format: str = "json",
) -> str:
    """Export the knowledge graph (nodes and edges).

    Args:
        agent_name: Filter to a specific agent (None = all).
        format: Output format — 'json' or 'csv'.

    Returns:
        Absolute file path of the exported file.
    """
    _ensure_exports_dir()

    try:
        conn = _get_db("pagal.db")
        if agent_name:
            nodes = conn.execute(
                "SELECT * FROM knowledge_nodes WHERE agent_name = ? ORDER BY created_at DESC",
                (agent_name,),
            ).fetchall()
        else:
            nodes = conn.execute(
                "SELECT * FROM knowledge_nodes ORDER BY created_at DESC",
            ).fetchall()

        edges = conn.execute("SELECT * FROM knowledge_edges").fetchall()
        conn.close()
    except Exception as e:
        logger.warning("Could not read knowledge from pagal.db: %s", e)
        nodes, edges = [], []

    nodes_data = [dict(r) for r in nodes]
    edges_data = [dict(r) for r in edges]

    suffix = agent_name or "all"
    ext = "csv" if format == "csv" else "json"
    file_path = EXPORTS_DIR / f"knowledge_{suffix}_{_timestamp_str()}.{ext}"

    if format == "csv":
        # For CSV, export nodes only (edges are relational)
        return _write_csv(nodes_data, file_path)
    return _write_json({"nodes": nodes_data, "edges": edges_data}, file_path)


def export_memory(
    agent_name: str,
    format: str = "json",
) -> str:
    """Export an agent's cross-session memory.

    Args:
        agent_name: Agent whose memory to export.
        format: Output format — 'json' or 'csv'.

    Returns:
        Absolute file path of the exported file.
    """
    _ensure_exports_dir()

    try:
        conn = _get_db("pagal.db")
        messages = conn.execute(
            "SELECT * FROM agent_memory WHERE agent_name = ? ORDER BY created_at DESC",
            (agent_name,),
        ).fetchall()
        summaries = conn.execute(
            "SELECT * FROM memory_summaries WHERE agent_name = ? ORDER BY created_at DESC",
            (agent_name,),
        ).fetchall()
        conn.close()
    except Exception as e:
        logger.warning("Could not read memory from pagal.db: %s", e)
        messages, summaries = [], []

    messages_data = [dict(r) for r in messages]
    summaries_data = [dict(r) for r in summaries]

    ext = "csv" if format == "csv" else "json"
    file_path = EXPORTS_DIR / f"memory_{agent_name}_{_timestamp_str()}.{ext}"

    if format == "csv":
        return _write_csv(messages_data, file_path)
    return _write_json(
        {"messages": messages_data, "summaries": summaries_data}, file_path,
    )


def export_all(format: str = "json") -> str:
    """Export everything (traces, analytics, knowledge, memory) into a zip file.

    Args:
        format: Format for individual files inside the zip — 'json' or 'csv'.

    Returns:
        Absolute file path of the zip file.
    """
    _ensure_exports_dir()
    zip_path = EXPORTS_DIR / f"pagal_export_all_{_timestamp_str()}.zip"

    try:
        # Generate individual exports to temp paths
        traces_path = export_traces(format=format)
        analytics_path = export_analytics(format=format)
        knowledge_path = export_knowledge(format=format)

        # Get all agent names for memory export
        agent_names: list[str] = []
        try:
            conn = _get_db("pagal.db")
            rows = conn.execute(
                "SELECT DISTINCT agent_name FROM agent_memory",
            ).fetchall()
            conn.close()
            agent_names = [r["agent_name"] for r in rows]
        except Exception:
            pass

        memory_paths: list[str] = []
        for name in agent_names:
            try:
                memory_paths.append(export_memory(name, format=format))
            except Exception:
                pass

        # Bundle into zip
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(traces_path, Path(traces_path).name)
            zf.write(analytics_path, Path(analytics_path).name)
            zf.write(knowledge_path, Path(knowledge_path).name)
            for mp in memory_paths:
                zf.write(mp, Path(mp).name)

        # Clean up individual files
        for p in [traces_path, analytics_path, knowledge_path, *memory_paths]:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass

        logger.info("Exported all data to %s", zip_path)
        return str(zip_path)
    except Exception as e:
        logger.error("Failed to create full export: %s", e)
        raise
