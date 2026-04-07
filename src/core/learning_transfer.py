"""Agent Cloning with Learning Transfer — fork agents with their knowledge.

When you clone/fork an agent, it can inherit:
  - Memory (conversation history)
  - Facts (from smart_memory)
  - Knowledge graph entries
  - Performance data (what worked, what didn't)

This means forked agents start "experienced" instead of blank.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config

logger = logging.getLogger("pagal_os")


def clone_with_learning(
    source_name: str,
    new_name: str,
    transfer_memory: bool = True,
    transfer_facts: bool = True,
    transfer_knowledge: bool = True,
    personality_override: str = "",
) -> dict[str, Any]:
    """Clone an agent AND transfer its learned knowledge.

    Args:
        source_name: Source agent to clone.
        new_name: Name for the new agent.
        transfer_memory: Copy conversation history.
        transfer_facts: Copy smart memory facts.
        transfer_knowledge: Copy knowledge graph entries.
        personality_override: Optional new personality (keeps original if empty).

    Returns:
        Dict with 'ok', 'agent_name', and transfer stats.
    """
    try:
        config = get_config()

        # Load source agent YAML
        source_path = config.agents_dir / f"{source_name}.yaml"
        if not source_path.exists():
            return {"ok": False, "error": f"Source agent '{source_name}' not found"}

        new_path = config.agents_dir / f"{new_name}.yaml"
        if new_path.exists():
            return {"ok": False, "error": f"Agent '{new_name}' already exists"}

        with open(source_path, "r") as f:
            agent_data = yaml.safe_load(f) or {}

        # Update the clone
        agent_data["name"] = new_name
        if personality_override:
            agent_data["personality"] = personality_override

        # Add lineage metadata
        agent_data["forked_from"] = source_name
        agent_data["forked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        # Save new agent
        new_path.write_text(yaml.dump(agent_data, default_flow_style=False, sort_keys=False))

        stats = {"memory_messages": 0, "facts": 0, "knowledge_nodes": 0}

        # Transfer memory
        if transfer_memory:
            try:
                from src.core.database import get_connection
                conn = get_connection()
                try:
                    rows = conn.execute(
                        "SELECT session_id, role, content, importance FROM agent_memory WHERE agent_name = ? ORDER BY created_at DESC LIMIT 100",
                        (source_name,),
                    ).fetchall()
                    for row in rows:
                        conn.execute(
                            "INSERT INTO agent_memory (agent_name, session_id, role, content, importance) VALUES (?, ?, ?, ?, ?)",
                            (new_name, row["session_id"], row["role"], row["content"], row["importance"]),
                        )
                    conn.commit()
                    stats["memory_messages"] = len(rows)
                finally:
                    conn.close()
            except Exception as e:
                logger.debug("Memory transfer skipped: %s", e)

        # Transfer facts
        if transfer_facts:
            try:
                from src.core.smart_memory import get_facts, add_fact
                facts = get_facts(source_name)
                for fact in facts:
                    add_fact(
                        fact=fact["fact"],
                        agent_name=new_name,
                        category=fact.get("category", "general"),
                        confidence=fact.get("confidence", 0.8),
                        source=f"transferred_from:{source_name}",
                    )
                stats["facts"] = len(facts)
            except Exception as e:
                logger.debug("Facts transfer skipped: %s", e)

        # Transfer knowledge
        if transfer_knowledge:
            try:
                from src.core.database import get_connection
                conn = get_connection()
                try:
                    rows = conn.execute(
                        "SELECT topic, content, source FROM knowledge_nodes WHERE agent_name = ?",
                        (source_name,),
                    ).fetchall()
                    for row in rows:
                        conn.execute(
                            "INSERT INTO knowledge_nodes (agent_name, topic, content, source) VALUES (?, ?, ?, ?)",
                            (new_name, row["topic"], row["content"], f"transferred:{row['source']}"),
                        )
                    conn.commit()
                    stats["knowledge_nodes"] = len(rows)
                finally:
                    conn.close()
            except Exception as e:
                logger.debug("Knowledge transfer skipped: %s", e)

        logger.info(
            "Cloned '%s' → '%s' with learning: %d messages, %d facts, %d knowledge nodes",
            source_name, new_name, stats["memory_messages"], stats["facts"], stats["knowledge_nodes"],
        )

        return {
            "ok": True,
            "agent_name": new_name,
            "forked_from": source_name,
            "transferred": stats,
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_agent_lineage(agent_name: str) -> dict[str, Any]:
    """Get the lineage (fork history) of an agent.

    Returns:
        Dict with parent chain and fork info.
    """
    try:
        config = get_config()
        lineage: list[dict[str, str]] = []
        current = agent_name

        while current:
            agent_path = config.agents_dir / f"{current}.yaml"
            if not agent_path.exists():
                break

            with open(agent_path, "r") as f:
                data = yaml.safe_load(f) or {}

            lineage.append({
                "name": current,
                "forked_from": data.get("forked_from", ""),
                "forked_at": data.get("forked_at", ""),
            })
            current = data.get("forked_from", "")

        return {"ok": True, "lineage": lineage}

    except Exception as e:
        return {"ok": False, "error": str(e)}
