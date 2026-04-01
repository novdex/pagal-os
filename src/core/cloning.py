"""Agent Cloning & Forking — create modified copies of existing agents.

Clone agents to create exact copies, or fork them with modifications
to model, tools, or personality. Track lineage history so you can see
where each agent came from.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config

logger = logging.getLogger("pagal_os")


def clone_agent(source_name: str, new_name: str) -> bool:
    """Clone an agent to create an exact copy with a new name.

    Copies the agent YAML, preserves all tools, model, personality,
    and adds forked_from metadata pointing back to the source.

    Args:
        source_name: Name of the agent to clone (without .yaml).
        new_name: Name for the new cloned agent.

    Returns:
        True if cloned successfully, False otherwise.
    """
    try:
        config = get_config()
        source_path = config.agents_dir / f"{source_name}.yaml"
        dest_path = config.agents_dir / f"{new_name}.yaml"

        if not source_path.exists():
            logger.error("Source agent '%s' not found at %s", source_name, source_path)
            return False

        if dest_path.exists():
            logger.error("Agent '%s' already exists at %s", new_name, dest_path)
            return False

        # Load source YAML
        with open(source_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Update metadata for the clone
        data["name"] = new_name
        data["forked_from"] = source_name
        data["version"] = 1
        data["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Write new agent
        with open(dest_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        logger.info("Cloned agent '%s' -> '%s'", source_name, new_name)
        return True

    except Exception as e:
        logger.error("Failed to clone agent '%s': %s", source_name, e)
        return False


def fork_agent(source_name: str, new_name: str, changes: dict[str, Any]) -> bool:
    """Fork an agent: clone it and apply modifications.

    Supports changing model, adding/removing tools, modifying personality,
    updating description, etc.

    Args:
        source_name: Name of the agent to fork.
        new_name: Name for the forked agent.
        changes: Dict of fields to change, e.g.
                 {"model": "gpt-4", "tools": ["search_web"], "personality": "..."}.

    Returns:
        True if forked successfully, False otherwise.
    """
    try:
        config = get_config()
        source_path = config.agents_dir / f"{source_name}.yaml"
        dest_path = config.agents_dir / f"{new_name}.yaml"

        if not source_path.exists():
            logger.error("Source agent '%s' not found", source_name)
            return False

        if dest_path.exists():
            logger.error("Agent '%s' already exists", new_name)
            return False

        # Load source YAML
        with open(source_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Apply changes
        for key, value in changes.items():
            if key == "add_tools" and isinstance(value, list):
                # Merge new tools into existing list
                existing = data.get("tools", [])
                data["tools"] = list(set(existing + value))
            elif key == "remove_tools" and isinstance(value, list):
                # Remove specified tools
                existing = data.get("tools", [])
                data["tools"] = [t for t in existing if t not in value]
            else:
                data[key] = value

        # Set fork metadata
        data["name"] = new_name
        data["forked_from"] = source_name
        data["version"] = 1
        data["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Write new agent
        with open(dest_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        logger.info(
            "Forked agent '%s' -> '%s' with changes: %s",
            source_name, new_name, list(changes.keys()),
        )
        return True

    except Exception as e:
        logger.error("Failed to fork agent '%s': %s", source_name, e)
        return False


def get_agent_history(agent_name: str) -> list[dict[str, Any]]:
    """Show the clone/fork lineage of an agent.

    Traces back through forked_from metadata to build a full history
    chain from the original to the current agent.

    Args:
        agent_name: Name of the agent to trace.

    Returns:
        List of dicts with name, forked_from, version, and created_at
        for each ancestor, ordered from oldest to newest.
    """
    try:
        config = get_config()
        history: list[dict[str, Any]] = []
        visited: set[str] = set()
        current_name = agent_name

        while current_name and current_name not in visited:
            visited.add(current_name)
            agent_path = config.agents_dir / f"{current_name}.yaml"

            if not agent_path.exists():
                # If we can't find the ancestor, note it and stop
                history.append({
                    "name": current_name,
                    "forked_from": None,
                    "version": "?",
                    "created_at": "unknown",
                    "exists": False,
                })
                break

            with open(agent_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            history.append({
                "name": current_name,
                "forked_from": data.get("forked_from"),
                "version": data.get("version", 1),
                "created_at": data.get("created_at", "unknown"),
                "exists": True,
            })

            current_name = data.get("forked_from")

        # Reverse so oldest ancestor is first
        history.reverse()
        return history

    except Exception as e:
        logger.error("Failed to get history for '%s': %s", agent_name, e)
        return []


def diff_agents(agent_a: str, agent_b: str) -> dict[str, Any]:
    """Show differences between two agents.

    Compares model, tools, personality, description, schedule,
    and any other YAML fields.

    Args:
        agent_a: First agent name.
        agent_b: Second agent name.

    Returns:
        Dict with "ok" bool and "differences" list. Each difference
        is a dict with field, value_a, and value_b.
    """
    try:
        config = get_config()
        path_a = config.agents_dir / f"{agent_a}.yaml"
        path_b = config.agents_dir / f"{agent_b}.yaml"

        if not path_a.exists():
            return {"ok": False, "error": f"Agent '{agent_a}' not found"}
        if not path_b.exists():
            return {"ok": False, "error": f"Agent '{agent_b}' not found"}

        with open(path_a, "r", encoding="utf-8") as f:
            data_a = yaml.safe_load(f) or {}
        with open(path_b, "r", encoding="utf-8") as f:
            data_b = yaml.safe_load(f) or {}

        # Collect all keys from both agents
        all_keys = sorted(set(list(data_a.keys()) + list(data_b.keys())))

        # Skip metadata-only fields from the diff
        skip_fields = {"name", "forked_from", "created_at", "version"}

        differences: list[dict[str, Any]] = []
        for key in all_keys:
            if key in skip_fields:
                continue
            val_a = data_a.get(key)
            val_b = data_b.get(key)
            if val_a != val_b:
                differences.append({
                    "field": key,
                    "value_a": val_a,
                    "value_b": val_b,
                })

        return {
            "ok": True,
            "agent_a": agent_a,
            "agent_b": agent_b,
            "differences": differences,
            "identical": len(differences) == 0,
        }

    except Exception as e:
        logger.error("Failed to diff agents: %s", e)
        return {"ok": False, "error": str(e)}
