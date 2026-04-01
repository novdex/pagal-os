"""Agent Registry — unique identity and permissions for every agent.

Each agent gets a unique ID, signed certificate, and permission manifest.
Persisted in ~/.pagal-os/registry.json.
"""

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Storage
_PAGAL_DIR = Path.home() / ".pagal-os"
REGISTRY_FILE = _PAGAL_DIR / "registry.json"

# Default permissions for newly registered agents
_DEFAULT_PERMISSIONS: dict[str, Any] = {
    "allowed_tools": ["search_web", "browse_url", "read_file", "write_file"],
    "denied_tools": [],
    "file_access": ["~/.pagal-os/", "/tmp/"],
    "network_access": True,
    "requires_approval": False,
    "max_budget_daily": 1.0,
}


def _ensure_registry() -> None:
    """Create the registry file if it doesn't exist."""
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        if not REGISTRY_FILE.exists():
            REGISTRY_FILE.write_text(
                json.dumps({}, indent=2), encoding="utf-8",
            )
            logger.info("Created agent registry at %s", REGISTRY_FILE)
    except Exception as e:
        logger.error("Failed to initialise agent registry: %s", e)


def _load_registry() -> dict[str, Any]:
    """Load the full registry from disk.

    Returns:
        Dict mapping agent_name -> identity record.
    """
    _ensure_registry()
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("Failed to load registry: %s", e)
        return {}


def _save_registry(registry: dict[str, Any]) -> None:
    """Persist the registry to disk.

    Args:
        registry: Full registry dict.
    """
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        REGISTRY_FILE.write_text(
            json.dumps(registry, indent=2), encoding="utf-8",
        )
    except Exception as e:
        logger.error("Failed to save registry: %s", e)


def register_agent(agent_name: str) -> dict[str, Any]:
    """Register an agent with a unique ID and permission manifest.

    If already registered, returns existing identity without overwriting.

    Args:
        agent_name: Name of the agent to register.

    Returns:
        Dict with agent_id, name, permissions, registered_at, status.
    """
    try:
        registry = _load_registry()

        # If already registered, return existing
        if agent_name in registry:
            logger.debug("Agent '%s' already registered", agent_name)
            return registry[agent_name]

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        agent_id = str(uuid.uuid4())

        identity: dict[str, Any] = {
            "agent_id": agent_id,
            "name": agent_name,
            "allowed_tools": list(_DEFAULT_PERMISSIONS["allowed_tools"]),
            "denied_tools": list(_DEFAULT_PERMISSIONS["denied_tools"]),
            "file_access": list(_DEFAULT_PERMISSIONS["file_access"]),
            "network_access": _DEFAULT_PERMISSIONS["network_access"],
            "requires_approval": _DEFAULT_PERMISSIONS["requires_approval"],
            "max_budget_daily": _DEFAULT_PERMISSIONS["max_budget_daily"],
            "registered_at": now,
            "last_active": now,
            "total_runs": 0,
            "status": "active",
        }

        registry[agent_name] = identity
        _save_registry(registry)
        logger.info("Registered agent '%s' with ID %s", agent_name, agent_id)
        return identity

    except Exception as e:
        logger.error("Failed to register agent '%s': %s", agent_name, e)
        return {}


def get_agent_identity(agent_name: str) -> dict[str, Any]:
    """Get the full identity record for an agent.

    Args:
        agent_name: Name of the agent.

    Returns:
        Dict with agent_id, name, permissions, registered_at, last_active,
        total_runs. Empty dict if not found.
    """
    try:
        registry = _load_registry()
        identity = registry.get(agent_name, {})
        return identity
    except Exception as e:
        logger.error("Failed to get identity for '%s': %s", agent_name, e)
        return {}


def update_permissions(agent_name: str, permissions: dict[str, Any]) -> bool:
    """Update the permission manifest for an agent.

    Args:
        agent_name: Name of the agent.
        permissions: Dict of permission keys to update (partial update).

    Returns:
        True if updated successfully, False otherwise.
    """
    try:
        registry = _load_registry()

        if agent_name not in registry:
            logger.warning("Agent '%s' not found in registry", agent_name)
            return False

        allowed_keys = {
            "allowed_tools", "denied_tools", "file_access",
            "network_access", "requires_approval", "max_budget_daily",
        }

        for key, value in permissions.items():
            if key in allowed_keys:
                registry[agent_name][key] = value

        _save_registry(registry)
        logger.info("Updated permissions for agent '%s'", agent_name)
        return True

    except Exception as e:
        logger.error("Failed to update permissions for '%s': %s", agent_name, e)
        return False


def verify_agent(agent_name: str) -> bool:
    """Check if an agent is registered and active.

    Args:
        agent_name: Name of the agent.

    Returns:
        True if registered and status is 'active'.
    """
    try:
        registry = _load_registry()
        if agent_name not in registry:
            return False
        return registry[agent_name].get("status") == "active"
    except Exception as e:
        logger.error("Failed to verify agent '%s': %s", agent_name, e)
        return False


def list_registered() -> list[dict[str, Any]]:
    """List all registered agents with their identities.

    Returns:
        List of identity dicts for all registered agents.
    """
    try:
        registry = _load_registry()
        return list(registry.values())
    except Exception as e:
        logger.error("Failed to list registered agents: %s", e)
        return []


def revoke_agent(agent_name: str) -> bool:
    """Deactivate an agent's identity.

    Sets the agent's status to 'revoked'. Does not delete the record.

    Args:
        agent_name: Name of the agent to revoke.

    Returns:
        True if revoked, False if not found.
    """
    try:
        registry = _load_registry()

        if agent_name not in registry:
            logger.warning("Agent '%s' not found in registry", agent_name)
            return False

        registry[agent_name]["status"] = "revoked"
        _save_registry(registry)
        logger.info("Revoked agent '%s'", agent_name)
        return True

    except Exception as e:
        logger.error("Failed to revoke agent '%s': %s", agent_name, e)
        return False


def get_permission_manifest(agent_name: str) -> dict[str, Any]:
    """Get the full permission manifest for an agent.

    Args:
        agent_name: Name of the agent.

    Returns:
        Dict with tools, file access, network, approval, and budget permissions.
        Empty dict if not found.
    """
    try:
        registry = _load_registry()
        if agent_name not in registry:
            return {}

        identity = registry[agent_name]
        return {
            "agent_id": identity.get("agent_id", ""),
            "name": identity.get("name", agent_name),
            "allowed_tools": identity.get("allowed_tools", []),
            "denied_tools": identity.get("denied_tools", []),
            "file_access": identity.get("file_access", []),
            "network_access": identity.get("network_access", True),
            "requires_approval": identity.get("requires_approval", False),
            "max_budget_daily": identity.get("max_budget_daily", 1.0),
            "registered_at": identity.get("registered_at", ""),
            "status": identity.get("status", "unknown"),
        }

    except Exception as e:
        logger.error(
            "Failed to get permission manifest for '%s': %s", agent_name, e,
        )
        return {}


def record_agent_run(agent_name: str) -> None:
    """Record that an agent ran (updates last_active and total_runs).

    Auto-registers the agent if not already registered.

    Args:
        agent_name: Name of the agent.
    """
    try:
        registry = _load_registry()

        if agent_name not in registry:
            # Auto-register on first run
            register_agent(agent_name)
            registry = _load_registry()

        if agent_name in registry:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            registry[agent_name]["last_active"] = now
            registry[agent_name]["total_runs"] = (
                registry[agent_name].get("total_runs", 0) + 1
            )
            _save_registry(registry)

    except Exception as e:
        logger.debug("Failed to record agent run for '%s': %s", agent_name, e)
