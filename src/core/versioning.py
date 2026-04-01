"""PAGAL OS Agent Versioning — git-like version control for agent configs.

Every time an agent YAML is modified (fork, config change, etc.), the previous
version is saved. Users can list versions, roll back, diff, and inspect any
historical snapshot.

Storage: ~/.pagal-os/versions/{agent_name}/v{N}.yaml
"""

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config

logger = logging.getLogger("pagal_os")

# Versions root directory
VERSIONS_DIR = Path.home() / ".pagal-os" / "versions"


def _versions_dir(agent_name: str) -> Path:
    """Get the versions directory for a specific agent.

    Args:
        agent_name: Name of the agent.

    Returns:
        Path to the agent's versions directory.
    """
    d = VERSIONS_DIR / agent_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _agent_yaml_path(agent_name: str) -> Path:
    """Get the path to an agent's current YAML config.

    Args:
        agent_name: Name of the agent.

    Returns:
        Path to the agent's YAML file.
    """
    config = get_config()
    return config.agents_dir / f"{agent_name}.yaml"


def _next_version(agent_name: str) -> int:
    """Determine the next version number for an agent.

    Args:
        agent_name: Name of the agent.

    Returns:
        The next version number (1-based).
    """
    d = _versions_dir(agent_name)
    existing = sorted(d.glob("v*.yaml"))
    if not existing:
        return 1
    # Extract the highest version number
    max_v = 0
    for f in existing:
        try:
            v = int(f.stem.lstrip("v"))
            max_v = max(max_v, v)
        except ValueError:
            continue
    return max_v + 1


def save_version(agent_name: str) -> int:
    """Copy current agent YAML to the versions directory.

    Args:
        agent_name: Name of the agent.

    Returns:
        The version number that was saved.

    Raises:
        FileNotFoundError: If the agent YAML doesn't exist.
    """
    try:
        src = _agent_yaml_path(agent_name)
        if not src.exists():
            raise FileNotFoundError(f"Agent YAML not found: {src}")

        version = _next_version(agent_name)
        dest = _versions_dir(agent_name) / f"v{version}.yaml"
        shutil.copy2(src, dest)

        # Save metadata alongside
        meta_path = _versions_dir(agent_name) / f"v{version}.meta.json"
        meta = {
            "version": version,
            "agent_name": agent_name,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "size_bytes": src.stat().st_size,
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        logger.info("Saved version %d for agent '%s'", version, agent_name)
        return version
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to save version for '%s': %s", agent_name, e)
        raise


def list_versions(agent_name: str) -> list[dict[str, Any]]:
    """Return all saved versions for an agent.

    Args:
        agent_name: Name of the agent.

    Returns:
        List of dicts with version_number, date, and size.
    """
    try:
        d = _versions_dir(agent_name)
        versions: list[dict[str, Any]] = []

        for f in sorted(d.glob("v*.yaml")):
            if f.stem.endswith(".meta"):
                continue
            try:
                v_num = int(f.stem.lstrip("v"))
            except ValueError:
                continue

            # Try loading metadata
            meta_path = d / f"v{v_num}.meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    versions.append({
                        "version": v_num,
                        "date": meta.get("saved_at", ""),
                        "size_bytes": meta.get("size_bytes", f.stat().st_size),
                    })
                    continue
                except Exception:
                    pass

            # Fallback to file stats
            stat = f.stat()
            versions.append({
                "version": v_num,
                "date": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "size_bytes": stat.st_size,
            })

        return versions
    except Exception as e:
        logger.error("Failed to list versions for '%s': %s", agent_name, e)
        return []


def rollback(agent_name: str, version: int) -> bool:
    """Restore an agent YAML from a previous version.

    Saves the current version first (auto-version), then overwrites with
    the specified historical version.

    Args:
        agent_name: Name of the agent.
        version: Version number to restore.

    Returns:
        True if rolled back successfully, False otherwise.
    """
    try:
        version_file = _versions_dir(agent_name) / f"v{version}.yaml"
        if not version_file.exists():
            logger.warning("Version v%d not found for agent '%s'", version, agent_name)
            return False

        dest = _agent_yaml_path(agent_name)

        # Auto-save current version before overwriting
        if dest.exists():
            try:
                save_version(agent_name)
            except Exception as e:
                logger.debug("Auto-version before rollback failed: %s", e)

        shutil.copy2(version_file, dest)
        logger.info("Rolled back agent '%s' to version %d", agent_name, version)
        return True
    except Exception as e:
        logger.error("Rollback failed for '%s' v%d: %s", agent_name, version, e)
        return False


def get_version(agent_name: str, version: int) -> dict[str, Any]:
    """Return the YAML content of a specific version.

    Args:
        agent_name: Name of the agent.
        version: Version number to retrieve.

    Returns:
        Dict with the parsed YAML content, or error dict.
    """
    try:
        version_file = _versions_dir(agent_name) / f"v{version}.yaml"
        if not version_file.exists():
            return {"ok": False, "error": f"Version v{version} not found for '{agent_name}'"}

        content = version_file.read_text(encoding="utf-8")
        data = yaml.safe_load(content) or {}
        return {"ok": True, "version": version, "content": data, "raw": content}
    except Exception as e:
        logger.error("Failed to get version v%d for '%s': %s", version, agent_name, e)
        return {"ok": False, "error": str(e)}


def diff_versions(agent_name: str, v1: int, v2: int) -> dict[str, Any]:
    """Show differences between two versions of an agent.

    Args:
        agent_name: Name of the agent.
        v1: First version number.
        v2: Second version number.

    Returns:
        Dict with list of differences or error.
    """
    try:
        data1 = get_version(agent_name, v1)
        data2 = get_version(agent_name, v2)

        if not data1.get("ok"):
            return {"ok": False, "error": f"Version v{v1} not found"}
        if not data2.get("ok"):
            return {"ok": False, "error": f"Version v{v2} not found"}

        content1 = data1["content"]
        content2 = data2["content"]

        # Compare all keys from both versions
        all_keys = set(list(content1.keys()) + list(content2.keys()))
        differences: list[dict[str, Any]] = []

        for key in sorted(all_keys):
            val1 = content1.get(key)
            val2 = content2.get(key)
            if val1 != val2:
                differences.append({
                    "field": key,
                    f"v{v1}": val1,
                    f"v{v2}": val2,
                })

        return {
            "ok": True,
            "agent_name": agent_name,
            "v1": v1,
            "v2": v2,
            "identical": len(differences) == 0,
            "differences": differences,
        }
    except Exception as e:
        logger.error("Diff failed for '%s' v%d vs v%d: %s", agent_name, v1, v2, e)
        return {"ok": False, "error": str(e)}


def auto_version(agent_name: str) -> None:
    """Automatically save a version before an agent is modified.

    Call this before any operation that changes an agent's YAML (fork,
    config update, etc.). Silently does nothing if the agent doesn't exist.

    Args:
        agent_name: Name of the agent.
    """
    try:
        agent_path = _agent_yaml_path(agent_name)
        if agent_path.exists():
            save_version(agent_name)
    except Exception as e:
        logger.debug("Auto-version for '%s' failed (non-critical): %s", agent_name, e)
