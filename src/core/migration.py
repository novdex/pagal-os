"""PAGAL OS Agent Migration — export/import agents across machines.

Creates self-contained ``.pagal`` migration packages (actually zip files)
containing an agent's YAML config, memory, knowledge, version history,
and registry entry. The package can be moved to another machine and
imported with full fidelity.

Migration package format::

    agent_migration.pagal/
    ├── agent.yaml          # Agent config
    ├── memory.json         # All memory messages
    ├── knowledge.json      # Knowledge nodes and edges
    ├── versions/           # Version history YAMLs
    ├── registry.json       # Identity and permissions
    └── manifest.json       # Package metadata
"""

import json
import logging
import platform
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config

logger = logging.getLogger("pagal_os")

# Paths
_PAGAL_DIR = Path.home() / ".pagal-os"
MIGRATIONS_DIR = _PAGAL_DIR / "migrations"


def _ensure_migrations_dir() -> None:
    """Create the migrations directory if it doesn't exist."""
    try:
        MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error("Failed to create migrations directory: %s", e)


def _get_db(db_name: str) -> sqlite3.Connection:
    """Open a SQLite database from the PAGAL OS storage directory.

    Args:
        db_name: Database filename.

    Returns:
        sqlite3 Connection with row_factory set to Row.
    """
    db_path = _PAGAL_DIR / db_name
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def export_agent_full(agent_name: str) -> str:
    """Create a full migration package for an agent.

    The package (.pagal file) contains the agent's YAML, memory,
    knowledge, version history, and registry entry.

    Args:
        agent_name: Name of the agent to export.

    Returns:
        Absolute path to the created .pagal migration package.

    Raises:
        FileNotFoundError: If the agent YAML doesn't exist.
    """
    _ensure_migrations_dir()
    config = get_config()

    # Verify agent exists
    agent_path = config.agents_dir / f"{agent_name}.yaml"
    if not agent_path.exists():
        raise FileNotFoundError(f"Agent '{agent_name}' not found at {agent_path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    package_name = f"{agent_name}_{timestamp}.pagal"
    package_path = MIGRATIONS_DIR / package_name

    try:
        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Agent YAML
            zf.write(agent_path, "agent.yaml")

            # 2. Memory (from pagal.db)
            memory_data: dict[str, Any] = {"messages": [], "summaries": []}
            try:
                conn = _get_db("pagal.db")
                messages = conn.execute(
                    "SELECT * FROM agent_memory WHERE agent_name = ? ORDER BY created_at",
                    (agent_name,),
                ).fetchall()
                summaries = conn.execute(
                    "SELECT * FROM memory_summaries WHERE agent_name = ? ORDER BY created_at",
                    (agent_name,),
                ).fetchall()
                conn.close()
                memory_data["messages"] = [dict(r) for r in messages]
                memory_data["summaries"] = [dict(r) for r in summaries]
            except Exception as e:
                logger.warning("Could not export memory for '%s': %s", agent_name, e)

            zf.writestr("memory.json", json.dumps(memory_data, indent=2, default=str))

            # 3. Knowledge (from pagal.db)
            knowledge_data: dict[str, Any] = {"nodes": [], "edges": []}
            try:
                conn = _get_db("pagal.db")
                nodes = conn.execute(
                    "SELECT * FROM knowledge_nodes WHERE agent_name = ? ORDER BY created_at",
                    (agent_name,),
                ).fetchall()
                # Get edges that reference this agent's nodes
                node_ids = [r["id"] for r in nodes]
                edges = []
                if node_ids:
                    placeholders = ",".join("?" * len(node_ids))
                    edges = conn.execute(
                        f"SELECT * FROM knowledge_edges WHERE from_id IN ({placeholders}) OR to_id IN ({placeholders})",
                        node_ids + node_ids,
                    ).fetchall()
                conn.close()
                knowledge_data["nodes"] = [dict(r) for r in nodes]
                knowledge_data["edges"] = [dict(r) for r in edges]
            except Exception as e:
                logger.warning("Could not export knowledge for '%s': %s", agent_name, e)

            zf.writestr("knowledge.json", json.dumps(knowledge_data, indent=2, default=str))

            # 4. Version history
            versions_dir = _PAGAL_DIR / "versions" / agent_name
            if versions_dir.exists():
                for vfile in versions_dir.glob("*.yaml"):
                    zf.write(vfile, f"versions/{vfile.name}")

            # 5. Registry entry
            registry_data: dict[str, Any] = {}
            registry_file = _PAGAL_DIR / "registry.json"
            try:
                if registry_file.exists():
                    all_registry = json.loads(
                        registry_file.read_text(encoding="utf-8"),
                    )
                    if agent_name in all_registry:
                        registry_data = all_registry[agent_name]
            except Exception as e:
                logger.warning("Could not export registry for '%s': %s", agent_name, e)

            zf.writestr("registry.json", json.dumps(registry_data, indent=2, default=str))

            # 6. Manifest
            manifest = {
                "name": agent_name,
                "version": "1.0",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "source_machine": platform.node(),
                "source_os": platform.system(),
                "pagal_os_version": "0.1",
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        logger.info("Migration package created: %s", package_path)
        return str(package_path)
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to create migration package: %s", e)
        # Clean up partial file
        package_path.unlink(missing_ok=True)
        raise


def validate_package(package_path: str) -> dict[str, Any]:
    """Validate a migration package without importing it.

    Args:
        package_path: Path to the .pagal file.

    Returns:
        Dict with 'valid' bool, 'errors' list, and 'manifest' if valid.
    """
    path = Path(package_path)
    errors: list[str] = []

    if not path.exists():
        return {"valid": False, "errors": ["File not found"], "manifest": None}

    if not path.suffix == ".pagal":
        errors.append("File extension should be .pagal")

    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()

            required = ["agent.yaml", "manifest.json"]
            for req in required:
                if req not in names:
                    errors.append(f"Missing required file: {req}")

            # Try to read manifest
            manifest = None
            if "manifest.json" in names:
                try:
                    manifest = json.loads(zf.read("manifest.json"))
                except Exception:
                    errors.append("Invalid manifest.json")

            # Try to parse agent YAML
            if "agent.yaml" in names:
                try:
                    yaml.safe_load(zf.read("agent.yaml"))
                except Exception:
                    errors.append("Invalid agent.yaml")

            return {
                "valid": len(errors) == 0,
                "errors": errors,
                "manifest": manifest,
                "files": names,
            }
    except zipfile.BadZipFile:
        return {"valid": False, "errors": ["Not a valid zip/pagal file"], "manifest": None}
    except Exception as e:
        return {"valid": False, "errors": [str(e)], "manifest": None}


def get_migration_info(package_path: str) -> dict[str, Any]:
    """Preview what's inside a migration package without importing.

    Args:
        package_path: Path to the .pagal file.

    Returns:
        Dict with package contents summary.
    """
    validation = validate_package(package_path)
    if not validation["valid"]:
        return {"ok": False, "errors": validation["errors"]}

    path = Path(package_path)
    info: dict[str, Any] = {
        "ok": True,
        "manifest": validation["manifest"],
        "files": validation.get("files", []),
    }

    try:
        with zipfile.ZipFile(path, "r") as zf:
            # Count memory messages
            if "memory.json" in zf.namelist():
                try:
                    memory = json.loads(zf.read("memory.json"))
                    info["memory_messages"] = len(memory.get("messages", []))
                    info["memory_summaries"] = len(memory.get("summaries", []))
                except Exception:
                    info["memory_messages"] = 0

            # Count knowledge nodes
            if "knowledge.json" in zf.namelist():
                try:
                    knowledge = json.loads(zf.read("knowledge.json"))
                    info["knowledge_nodes"] = len(knowledge.get("nodes", []))
                    info["knowledge_edges"] = len(knowledge.get("edges", []))
                except Exception:
                    info["knowledge_nodes"] = 0

            # Count versions
            version_files = [n for n in zf.namelist() if n.startswith("versions/")]
            info["versions_count"] = len(version_files)

            # Check registry
            info["has_registry"] = "registry.json" in zf.namelist()

            # Package size
            info["size_mb"] = round(path.stat().st_size / (1024 * 1024), 2)
    except Exception as e:
        info["warning"] = str(e)

    return info


def import_agent_full(package_path: str) -> dict[str, Any]:
    """Import a full migration package and restore the agent.

    Restores the agent YAML, memory, knowledge, version history,
    and registry entry from the .pagal package.

    Args:
        package_path: Path to the .pagal migration package.

    Returns:
        Dict with 'ok', 'agent' name, and 'imported' list of what was restored.

    Raises:
        FileNotFoundError: If the package file doesn't exist.
        ValueError: If the package is invalid.
    """
    # Validate first
    validation = validate_package(package_path)
    if not validation["valid"]:
        raise ValueError(f"Invalid migration package: {', '.join(validation['errors'])}")

    config = get_config()
    path = Path(package_path)
    imported: list[str] = []

    try:
        with zipfile.ZipFile(path, "r") as zf:
            # Read manifest for agent name
            manifest = json.loads(zf.read("manifest.json"))
            agent_name = manifest.get("name", "imported_agent")

            # 1. Restore agent YAML
            agent_yaml_data = zf.read("agent.yaml")
            agent_dest = config.agents_dir / f"{agent_name}.yaml"
            agent_dest.parent.mkdir(parents=True, exist_ok=True)
            agent_dest.write_bytes(agent_yaml_data)
            imported.append("agent.yaml")

            # 2. Restore memory
            if "memory.json" in zf.namelist():
                try:
                    memory = json.loads(zf.read("memory.json"))
                    conn = _get_db("pagal.db")

                    # Ensure tables exist
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS agent_memory (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            agent_name TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT NOT NULL,
                            importance REAL DEFAULT 0.5,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS memory_summaries (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            agent_name TEXT NOT NULL,
                            summary TEXT NOT NULL,
                            message_count INTEGER DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    for msg in memory.get("messages", []):
                        conn.execute(
                            "INSERT INTO agent_memory (agent_name, session_id, role, content, importance, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                agent_name,
                                msg.get("session_id", ""),
                                msg.get("role", ""),
                                msg.get("content", ""),
                                msg.get("importance", 0.5),
                                msg.get("created_at", ""),
                            ),
                        )
                    for summary in memory.get("summaries", []):
                        conn.execute(
                            "INSERT INTO memory_summaries (agent_name, summary, message_count, created_at) VALUES (?, ?, ?, ?)",
                            (
                                agent_name,
                                summary.get("summary", ""),
                                summary.get("message_count", 0),
                                summary.get("created_at", ""),
                            ),
                        )
                    conn.commit()
                    conn.close()
                    imported.append("memory")
                except Exception as e:
                    logger.warning("Failed to restore memory: %s", e)

            # 3. Restore knowledge
            if "knowledge.json" in zf.namelist():
                try:
                    knowledge = json.loads(zf.read("knowledge.json"))
                    conn = _get_db("pagal.db")

                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS knowledge_nodes (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            agent_name TEXT NOT NULL,
                            topic TEXT NOT NULL,
                            content TEXT NOT NULL,
                            source TEXT DEFAULT '',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS knowledge_edges (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            from_id INTEGER REFERENCES knowledge_nodes(id),
                            to_id INTEGER REFERENCES knowledge_nodes(id),
                            relation TEXT DEFAULT 'related_to',
                            weight REAL DEFAULT 1.0
                        )
                    """)

                    # Map old IDs to new IDs for edge restoration
                    id_map: dict[int, int] = {}
                    for node in knowledge.get("nodes", []):
                        cursor = conn.execute(
                            "INSERT INTO knowledge_nodes (agent_name, topic, content, source, created_at) VALUES (?, ?, ?, ?, ?)",
                            (
                                agent_name,
                                node.get("topic", ""),
                                node.get("content", ""),
                                node.get("source", ""),
                                node.get("created_at", ""),
                            ),
                        )
                        old_id = node.get("id")
                        if old_id is not None:
                            id_map[old_id] = cursor.lastrowid  # type: ignore[assignment]

                    for edge in knowledge.get("edges", []):
                        old_from = edge.get("from_id")
                        old_to = edge.get("to_id")
                        new_from = id_map.get(old_from)
                        new_to = id_map.get(old_to)
                        if new_from and new_to:
                            conn.execute(
                                "INSERT INTO knowledge_edges (from_id, to_id, relation, weight) VALUES (?, ?, ?, ?)",
                                (new_from, new_to, edge.get("relation", "related_to"), edge.get("weight", 1.0)),
                            )

                    conn.commit()
                    conn.close()
                    imported.append("knowledge")
                except Exception as e:
                    logger.warning("Failed to restore knowledge: %s", e)

            # 4. Restore version history
            version_files = [n for n in zf.namelist() if n.startswith("versions/") and n.endswith(".yaml")]
            if version_files:
                versions_dest = _PAGAL_DIR / "versions" / agent_name
                versions_dest.mkdir(parents=True, exist_ok=True)
                for vf in version_files:
                    vf_name = Path(vf).name
                    dest = versions_dest / vf_name
                    dest.write_bytes(zf.read(vf))
                imported.append(f"versions ({len(version_files)} files)")

            # 5. Restore registry entry
            if "registry.json" in zf.namelist():
                try:
                    registry_data = json.loads(zf.read("registry.json"))
                    if registry_data:  # not empty
                        registry_file = _PAGAL_DIR / "registry.json"
                        all_registry: dict[str, Any] = {}
                        if registry_file.exists():
                            all_registry = json.loads(
                                registry_file.read_text(encoding="utf-8"),
                            )
                        all_registry[agent_name] = registry_data
                        registry_file.write_text(
                            json.dumps(all_registry, indent=2), encoding="utf-8",
                        )
                        imported.append("registry")
                except Exception as e:
                    logger.warning("Failed to restore registry: %s", e)

        logger.info("Imported agent '%s' from %s", agent_name, package_path)
        return {"ok": True, "agent": agent_name, "imported": imported}
    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        logger.error("Migration import failed: %s", e)
        return {"ok": False, "agent": "", "error": str(e), "imported": imported}
