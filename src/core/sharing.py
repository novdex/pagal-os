"""PAGAL OS Agent Sharing — export, import, and share agents with short codes.

For the MVP (no central server), this generates self-contained JSON files that
can be transferred manually. A short share code is stored locally so agents can
be looked up by code on the same machine.

Storage:
    - Shared exports: ``~/.pagal-os/shared/{agent_name}.json``
    - Code registry: ``~/.pagal-os/share_codes.json``
"""

import json
import logging
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config

logger = logging.getLogger("pagal_os")

SHARED_DIR = Path.home() / ".pagal-os" / "shared"
SHARE_CODES_FILE = Path.home() / ".pagal-os" / "share_codes.json"


def _ensure_shared_dir() -> Path:
    """Ensure the shared exports directory exists.

    Returns:
        Path to the shared directory.
    """
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    return SHARED_DIR


def _load_share_codes() -> dict[str, Any]:
    """Load the share codes registry from disk.

    Returns:
        Dict mapping share codes to agent metadata.
    """
    try:
        if SHARE_CODES_FILE.exists():
            return json.loads(SHARE_CODES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load share codes: %s", e)
    return {}


def _save_share_codes(codes: dict[str, Any]) -> None:
    """Persist the share codes registry to disk.

    Args:
        codes: Dict mapping share codes to agent metadata.
    """
    try:
        SHARE_CODES_FILE.parent.mkdir(parents=True, exist_ok=True)
        SHARE_CODES_FILE.write_text(
            json.dumps(codes, indent=2), encoding="utf-8",
        )
    except Exception as e:
        logger.error("Failed to save share codes: %s", e)


def _generate_code(length: int = 8) -> str:
    """Generate a random alphanumeric share code.

    Args:
        length: Number of characters.

    Returns:
        Uppercase alphanumeric string.
    """
    charset = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(charset) for _ in range(length))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_agent(agent_name: str) -> str:
    """Create a shareable JSON file for an agent.

    The file contains the agent's YAML, metadata, version, and description
    in a self-contained format.

    Args:
        agent_name: Name of the agent to export.

    Returns:
        Absolute path to the exported JSON file.

    Raises:
        FileNotFoundError: If the agent YAML doesn't exist.
    """
    try:
        config = get_config()
        agent_path = config.agents_dir / f"{agent_name}.yaml"

        if not agent_path.exists():
            raise FileNotFoundError(f"Agent not found: {agent_path}")

        yaml_content = agent_path.read_text(encoding="utf-8")
        agent_data = yaml.safe_load(yaml_content) or {}

        share_code = generate_share_code(agent_name)

        share_payload = {
            "pagal_os_version": "0.1",
            "agent": {
                "name": agent_data.get("name", agent_name),
                "description": agent_data.get("description", ""),
                "yaml": yaml_content,
            },
            "shared_at": datetime.now(timezone.utc).isoformat(),
            "share_code": share_code,
        }

        out_dir = _ensure_shared_dir()
        out_path = out_dir / f"{agent_name}.json"
        out_path.write_text(json.dumps(share_payload, indent=2), encoding="utf-8")

        logger.info("Exported agent '%s' to %s (code: %s)", agent_name, out_path, share_code)
        return str(out_path)
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to export agent '%s': %s", agent_name, e)
        raise


def import_agent(file_path: str) -> str:
    """Import an agent from a shared JSON file.

    Reads the JSON, extracts the YAML content, and saves it to the agents
    directory.

    Args:
        file_path: Path to the shared JSON file.

    Returns:
        Name of the imported agent.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the JSON format is invalid.
    """
    try:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Share file not found: {file_path}")

        data = json.loads(p.read_text(encoding="utf-8"))

        agent_section = data.get("agent")
        if not agent_section or "yaml" not in agent_section:
            raise ValueError("Invalid share file format: missing 'agent.yaml' field")

        agent_name = agent_section.get("name", p.stem)
        yaml_content = agent_section["yaml"]

        config = get_config()
        dest = config.agents_dir / f"{agent_name}.yaml"
        dest.write_text(yaml_content, encoding="utf-8")

        logger.info("Imported agent '%s' from %s", agent_name, file_path)
        return agent_name
    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        logger.error("Failed to import agent from '%s': %s", file_path, e)
        raise


def generate_share_code(agent_name: str) -> str:
    """Create a short shareable code for an agent.

    If the agent already has a code, return the existing one.

    Args:
        agent_name: Name of the agent.

    Returns:
        8-character uppercase alphanumeric share code.
    """
    try:
        codes = _load_share_codes()

        # Check if this agent already has a code
        for code, meta in codes.items():
            if meta.get("agent_name") == agent_name:
                return code

        # Generate a new unique code
        code = _generate_code()
        while code in codes:
            code = _generate_code()

        codes[code] = {
            "agent_name": agent_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_share_codes(codes)

        logger.info("Generated share code '%s' for agent '%s'", code, agent_name)
        return code
    except Exception as e:
        logger.error("Failed to generate share code for '%s': %s", agent_name, e)
        # Return a code anyway so exports don't break
        return _generate_code()


def get_shared_agent(code: str) -> dict[str, Any] | None:
    """Look up an agent by its share code.

    Args:
        code: The 8-character share code.

    Returns:
        Dict with agent info if found, None otherwise.
    """
    try:
        codes = _load_share_codes()
        meta = codes.get(code.upper())
        if not meta:
            return None

        agent_name = meta.get("agent_name", "")

        # Try to load the shared JSON
        shared_file = SHARED_DIR / f"{agent_name}.json"
        if shared_file.exists():
            data = json.loads(shared_file.read_text(encoding="utf-8"))
            return data

        # If no shared file, try to build info from the agent YAML
        config = get_config()
        agent_path = config.agents_dir / f"{agent_name}.yaml"
        if agent_path.exists():
            yaml_content = agent_path.read_text(encoding="utf-8")
            agent_data = yaml.safe_load(yaml_content) or {}
            return {
                "pagal_os_version": "0.1",
                "agent": {
                    "name": agent_name,
                    "description": agent_data.get("description", ""),
                    "yaml": yaml_content,
                },
                "shared_at": meta.get("created_at", ""),
                "share_code": code.upper(),
            }

        return None
    except Exception as e:
        logger.error("Failed to get shared agent for code '%s': %s", code, e)
        return None
