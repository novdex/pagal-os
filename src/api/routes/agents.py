"""Agent CRUD, run, status, cloning, versioning, sharing, encryption routes."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.routes._models import (
    CloneAgentRequest,
    CreateAgentRequest,
    ForkAgentRequest,
    ImportAgentRequest,
    RunAgentRequest,
    SettingsUpdate,
)
from src.core.config import get_config
from src.core.creator import create_agent_from_description
from src.core.runtime import (
    delete_agent,
    get_agent_status,
    list_agents,
    load_agent,
    run_agent_async,
    stop_agent,
)
from src.core.sandbox import run_in_sandbox
from src.core.validators import (
    validate_agent_name,
    validate_file_path,
    validate_task,
)

logger = logging.getLogger("pagal_os")

router = APIRouter(tags=["agents"])


# --- Agent CRUD ---


@router.post("/api/agents")
async def api_create_agent(req: CreateAgentRequest) -> dict[str, Any]:
    """Create a new agent from a natural language description.

    Args:
        req: Request with description and optional model.

    Returns:
        Dict with agent name and success status.
    """
    try:
        valid, err = validate_task(req.description)
        if not valid:
            raise HTTPException(status_code=400, detail=err)

        name = create_agent_from_description(req.description, req.model)
        return {"ok": True, "name": name, "message": f"Agent '{name}' created"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create agent: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents")
async def api_list_agents() -> dict[str, Any]:
    """List all available agents.

    Returns:
        Dict with list of agent info dicts.
    """
    try:
        agents = list_agents()
        return {"ok": True, "agents": agents}
    except Exception as e:
        logger.error("Failed to list agents: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/agents/{name}/run")
async def api_run_agent(name: str, req: RunAgentRequest) -> dict[str, Any]:
    """Run an agent with a given task.

    Args:
        name: Agent name.
        req: Request with task and optional async_mode flag.

    Returns:
        AgentResult as dict if synchronous, or status message if async.
    """
    try:
        valid, err = validate_agent_name(name)
        if not valid:
            raise HTTPException(status_code=400, detail=err)
        valid, err = validate_task(req.task)
        if not valid:
            raise HTTPException(status_code=400, detail=err)

        if req.async_mode:
            result = run_agent_async(name, req.task)
            return {"ok": True, **result}

        agent = load_agent(name)
        result = run_in_sandbox(agent, req.task)
        return {
            "ok": result.ok,
            "output": result.output,
            "tools_used": result.tools_used,
            "duration_seconds": result.duration_seconds,
            "error": result.error,
        }
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except Exception as e:
        logger.error("Failed to run agent '%s': %s", name, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents/{name}/status")
async def api_agent_status(name: str) -> dict[str, Any]:
    """Get the status of an agent.

    Args:
        name: Agent name.

    Returns:
        Dict with agent status info.
    """
    try:
        status = get_agent_status(name)
        return {"ok": True, "name": name, **status}
    except Exception as e:
        logger.error("Failed to get status for '%s': %s", name, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/agents/{name}")
async def api_delete_agent(name: str) -> dict[str, Any]:
    """Delete an agent.

    Args:
        name: Agent name.

    Returns:
        Dict with success status.
    """
    if delete_agent(name):
        return {"ok": True, "message": f"Agent '{name}' deleted"}
    raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


@router.post("/api/agents/{name}/stop")
async def api_stop_agent(name: str) -> dict[str, Any]:
    """Stop a running agent.

    Args:
        name: Agent name.

    Returns:
        Dict with success status.
    """
    if stop_agent(name):
        return {"ok": True, "message": f"Agent '{name}' stopped"}
    return {"ok": False, "message": f"Agent '{name}' is not running"}


@router.get("/api/agents/{name}/logs")
async def api_agent_logs(name: str) -> dict[str, Any]:
    """Get logs for an agent.

    Args:
        name: Agent name.

    Returns:
        Dict with log entries.
    """
    config = get_config()
    log_file = config.logs_dir / f"{name}.log"

    if not log_file.exists():
        return {"ok": True, "logs": [], "message": "No logs yet"}

    try:
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        # Return last 100 lines
        return {"ok": True, "logs": lines[-100:]}
    except Exception as e:
        logger.error("Failed to read logs for '%s': %s", name, e)
        return {"ok": False, "logs": [], "error": str(e)}


@router.post("/api/settings", tags=["settings"])
async def api_update_settings(req: SettingsUpdate) -> dict[str, Any]:
    """Update runtime settings.

    Args:
        req: Settings to update.

    Returns:
        Dict with success status.
    """
    import os

    if req.openrouter_api_key is not None:
        os.environ["OPENROUTER_API_KEY"] = req.openrouter_api_key

    config = get_config()
    if req.default_model is not None:
        config.default_model = req.default_model
    if req.ollama_url is not None:
        config.ollama_url = req.ollama_url

    return {"ok": True, "message": "Settings updated"}


# --- Cloning & Forking ---


@router.post("/api/agents/{name}/clone")
async def api_clone_agent(name: str, req: CloneAgentRequest) -> dict[str, Any]:
    """Clone an agent to create an exact copy.

    Args:
        name: Source agent name.
        req: Request with new_name.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.cloning import clone_agent

        valid, err = validate_agent_name(name)
        if not valid:
            raise HTTPException(status_code=400, detail=f"Source name invalid: {err}")
        valid, err = validate_agent_name(req.new_name)
        if not valid:
            raise HTTPException(status_code=400, detail=f"New name invalid: {err}")

        if clone_agent(name, req.new_name):
            return {"ok": True, "message": f"Agent '{name}' cloned to '{req.new_name}'"}
        raise HTTPException(status_code=400, detail=f"Failed to clone '{name}'")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Clone error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/agents/{name}/fork")
async def api_fork_agent(name: str, req: ForkAgentRequest) -> dict[str, Any]:
    """Fork an agent with modifications.

    Args:
        name: Source agent name.
        req: Request with new_name and changes dict.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.cloning import fork_agent

        valid, err = validate_agent_name(name)
        if not valid:
            raise HTTPException(status_code=400, detail=f"Source name invalid: {err}")
        valid, err = validate_agent_name(req.new_name)
        if not valid:
            raise HTTPException(status_code=400, detail=f"New name invalid: {err}")

        if fork_agent(name, req.new_name, req.changes):
            return {"ok": True, "message": f"Agent '{name}' forked to '{req.new_name}'"}
        raise HTTPException(status_code=400, detail=f"Failed to fork '{name}'")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Fork error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Versioning ---


@router.get("/api/agents/{name}/versions", tags=["versioning"])
async def api_list_versions(name: str) -> dict[str, Any]:
    """List all saved versions for an agent.

    Args:
        name: Agent name.

    Returns:
        Dict with list of version info.
    """
    try:
        from src.core.versioning import list_versions
        versions = list_versions(name)
        return {"ok": True, "agent": name, "versions": versions}
    except Exception as e:
        logger.error("List versions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/agents/{name}/rollback/{version}", tags=["versioning"])
async def api_rollback_agent(name: str, version: int) -> dict[str, Any]:
    """Rollback an agent to a previous version.

    Args:
        name: Agent name.
        version: Version number to restore.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.versioning import rollback
        if rollback(name, version):
            return {"ok": True, "message": f"Agent '{name}' rolled back to v{version}"}
        raise HTTPException(
            status_code=404,
            detail=f"Version {version} not found for agent '{name}'",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Rollback error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents/{name}/versions/{version}", tags=["versioning"])
async def api_get_version(name: str, version: int) -> dict[str, Any]:
    """Get the content of a specific agent version.

    Args:
        name: Agent name.
        version: Version number.

    Returns:
        Dict with version content.
    """
    try:
        from src.core.versioning import get_version
        result = get_version(name, version)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get version error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents/{name}/versions/diff", tags=["versioning"])
async def api_diff_versions(name: str, v1: int = 1, v2: int = 2) -> dict[str, Any]:
    """Show differences between two versions of an agent.

    Args:
        name: Agent name.
        v1: First version number.
        v2: Second version number.

    Returns:
        Dict with differences.
    """
    try:
        from src.core.versioning import diff_versions
        return diff_versions(name, v1, v2)
    except Exception as e:
        logger.error("Diff versions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Sharing ---


@router.post("/api/agents/{name}/share", tags=["sharing"])
async def api_share_agent(name: str) -> dict[str, Any]:
    """Export an agent and generate a share code.

    Args:
        name: Agent name.

    Returns:
        Dict with share code and file path.
    """
    try:
        from src.core.sharing import export_agent
        import json as _json

        file_path = export_agent(name)
        data = _json.loads(Path(file_path).read_text(encoding="utf-8"))
        return {
            "ok": True,
            "share_code": data.get("share_code", ""),
            "file_path": file_path,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except Exception as e:
        logger.error("Share agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/agents/import", tags=["sharing"])
async def api_import_agent(req: ImportAgentRequest) -> dict[str, Any]:
    """Import an agent from a shared JSON file.

    Args:
        req: Request with file_path.

    Returns:
        Dict with imported agent name.
    """
    try:
        from src.core.sharing import import_agent

        valid, err = validate_file_path(req.file_path)
        if not valid:
            raise HTTPException(status_code=400, detail=err)

        name = import_agent(req.file_path)
        return {"ok": True, "name": name, "message": f"Agent '{name}' imported"}
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Share file not found")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("Import agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Encryption ---


@router.post("/api/agents/{name}/encrypt", tags=["encryption"])
async def api_encrypt_agent(name: str) -> dict[str, Any]:
    """Encrypt an agent's memory and config files.

    Args:
        name: Agent name.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.encryption import encrypt_agent_memory
        if encrypt_agent_memory(name):
            return {"ok": True, "message": f"Agent '{name}' encrypted"}
        return {"ok": False, "message": f"No files found to encrypt for '{name}'"}
    except Exception as e:
        logger.error("Encrypt agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents/{name}/decrypt", tags=["encryption"])
async def api_decrypt_agent(name: str) -> dict[str, Any]:
    """Decrypt and return an agent's encrypted files.

    Args:
        name: Agent name.

    Returns:
        Dict with decrypted file contents.
    """
    try:
        from src.core.encryption import decrypt_agent_memory
        results = decrypt_agent_memory(name)
        return {"ok": True, "files": results}
    except Exception as e:
        logger.error("Decrypt agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
